"""C8/R5 — two concurrent primary-excusal approvals promote the same reserve.

``decide_primary_excusal`` (approve) deletes the excused primary, picks the
first eligible reserve from an unlocked SELECT (``_eligible_assigned_reserves``)
and flips it to primary. No advisory/row lock serializes two approvals on the
same event, so both see the same single reserve.

Schedule reproduced here (two independent sessions = two duty managers' requests):
  1. approvals A and B (different primaries, same event, one reserve R) each
     delete their primary and SELECT the eligible reserves -> [R];
  2. both meet at a rendezvous right after that SELECT;
  3. both promote R and record it as their backfill, then commit (B's UPDATE
     of R waits for A's commit, then re-applies the same change).

Fixed (Task 3): ``decide_primary_excusal`` takes the per-date advisory lock
the other range roster writers use, then locks the request row, before reading
the eligible reserves. B blocks until A commits, A's rendezvous times out, and
B then finds no eligible reserve and takes the no-backfill path.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import (
    DutyType,
    RangeAssignment,
    RangeEvent,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeType,
    SystemSetting,
)
from app.services import range_excusal as excusal_service
from tests.helpers import create_node, create_range_location, create_soldier


def test_concurrent_excusal_approvals_promote_a_reserve_at_most_once(race, admin_session, monkeypatch):
    admin_session.add(SystemSetting(key="mitvachim.enabled", value=True))
    admin_session.commit()
    node = create_node(admin_session, level="branch", name="race-excusal")
    admin_session.add(DutyType(name="race-excusal weapon", score_per_day=Decimal("1.00"),
                               requires_weapon=True, eligible_node_ids=[node.id]))
    admin = create_soldier(admin_session, personal_number="race-exc-admin", role="admin")
    p1 = create_soldier(admin_session, personal_number="race-exc-p1", hierarchy_node_id=node.id)
    p2 = create_soldier(admin_session, personal_number="race-exc-p2", hierarchy_node_id=node.id)
    reserve = create_soldier(admin_session, personal_number="race-exc-r", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type=RangeType.laser, date=date.today() + timedelta(days=14),
        range_location_id=create_range_location(admin_session, name="race-excusal range").id,
        required_count=2, reserve_count=1,
    )
    admin_session.add(event)
    admin_session.flush()
    a1 = RangeAssignment(range_event_id=event.id, soldier_id=p1.id, is_reserve=False)
    a2 = RangeAssignment(range_event_id=event.id, soldier_id=p2.id, is_reserve=False)
    ar = RangeAssignment(range_event_id=event.id, soldier_id=reserve.id, is_reserve=True)
    admin_session.add_all([a1, a2, ar])
    admin_session.flush()
    r1 = RangeExcusalRequest(range_assignment_id=a1.id, range_event_id=event.id, requested_by=p1.id,
                             reason="sick", status=RangeExcusalStatus.pending)
    r2 = RangeExcusalRequest(range_assignment_id=a2.id, range_event_id=event.id, requested_by=p2.id,
                             reason="course", status=RangeExcusalStatus.pending)
    admin_session.add_all([r1, r2])
    admin_session.commit()
    event_id, reserve_assignment_id, request_ids = event.id, ar.id, (r1.id, r2.id)

    after_reserve_read = race.rendezvous(2, "both approvals read the eligible reserves")
    real_eligible = excusal_service._eligible_assigned_reserves

    def eligible_then_wait(session, **kwargs):
        rows = real_eligible(session, **kwargs)
        after_reserve_read.wait()
        return rows

    monkeypatch.setattr(excusal_service, "_eligible_assigned_reserves", eligible_then_wait)

    def approve(request_id):
        def _call():
            s = race.session()
            req = s.get(RangeExcusalRequest, request_id)
            return excusal_service.decide_primary_excusal(
                s, request=req, approve=True, decided_by=admin.id,
            ).promoted_assignment_id
        return _call

    outcomes = race.run(approve(request_ids[0]), approve(request_ids[1]))

    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"approval crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    promoted = admin_session.execute(
        select(RangeExcusalRequest.promoted_assignment_id).where(RangeExcusalRequest.id.in_(request_ids))
    ).scalars().all()
    primaries = admin_session.execute(
        select(RangeAssignment.id).where(RangeAssignment.range_event_id == event_id,
                                         RangeAssignment.is_reserve.is_(False))
    ).scalars().all()
    assert promoted.count(reserve_assignment_id) <= 1, (
        f"both approvals recorded reserve {reserve_assignment_id} as their backfill; "
        f"event now has {len(primaries)} primary assignment(s) for required_count=2"
    )
    assert sorted(promoted, key=lambda v: v is None) == [reserve_assignment_id, None]
