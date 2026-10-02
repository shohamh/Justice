"""C4 — range assignment-request approval bypasses the per-date lock (audit inventory R3).

``add_range_assignment`` serializes writers for one event date with
``pg_advisory_xact_lock(ns, event_date)`` before ``_check_capacity``.
``approve_assignment_request`` runs the same unlocked ``_check_capacity`` count
*without* that lock (and without locking the request row), so it is not
serialized against a manual add.

Schedule reproduced here (two independent sessions = two HTTP requests):
  1. request A (manual add, holds the date lock) and request B (approve a
     pending assignment request, no lock) each count 0 primaries on a
     required_count=1 event;
  2. both meet at a rendezvous right after ``_check_capacity`` returns;
  3. both insert a primary range_assignments row for different soldiers and
     commit.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import (
    DutyType,
    RangeAssignment,
    RangeAssignmentRequest,
    RangeEvent,
    RangeType,
    Soldier,
    SystemSetting,
)
from app.services import range_assignment_requests as request_service
from app.services import ranges as ranges_service
from tests.helpers import create_node, create_range_location, create_soldier


def _seed(session, *, required_count: int):
    session.add(SystemSetting(key="mitvachim.enabled", value=True))
    session.commit()
    node = create_node(session, level="branch", name="race-range-req")
    # A weapon duty type eligible for the node keeps the soldiers range-relevant
    # (otherwise is_range_exempt rejects them as structurally ineligible).
    session.add(DutyType(name="race-rr weapon", score_per_day=Decimal("1.00"),
                         requires_weapon=True, eligible_node_ids=[node.id]))
    admin = create_soldier(session, personal_number="race-rr-admin", role="admin")
    manual = create_soldier(session, personal_number="race-rr-manual", hierarchy_node_id=node.id)
    requested = create_soldier(session, personal_number="race-rr-requested", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type=RangeType.laser, date=date.today() + timedelta(days=14),
        range_location_id=create_range_location(session, name="race-rr range").id,
        required_count=required_count, reserve_count=0,
    )
    session.add(event)
    session.flush()
    req = RangeAssignmentRequest(range_event_id=event.id, soldier_id=requested.id, requested_by=admin.id,
                                 reason="needs qualification")
    session.add(req)
    session.commit()
    return event.id, req.id, admin.id, manual.id


def _race_add_vs_approve(race, monkeypatch, event_id, request_id, admin_id, manual_id):
    after_capacity_check = race.rendezvous(2, "add and approve both passed _check_capacity")
    real_check = ranges_service._check_capacity

    def check_then_wait(session, **kwargs):
        real_check(session, **kwargs)
        after_capacity_check.wait()

    # approve_assignment_request imports _check_capacity by name.
    monkeypatch.setattr(ranges_service, "_check_capacity", check_then_wait)
    monkeypatch.setattr(request_service, "_check_capacity", check_then_wait)

    def manual_add():
        s = race.session()
        event = s.get(RangeEvent, event_id)
        user = s.get(Soldier, admin_id)
        return ranges_service.add_range_assignment(s, event=event, soldier_id=manual_id, is_reserve=False, user=user)

    def approve_request():
        s = race.session()
        req = s.get(RangeAssignmentRequest, request_id)
        actor = s.get(Soldier, admin_id)
        return request_service.approve_assignment_request(s, request=req, actor=actor, is_reserve=False)

    return race.run(manual_add, approve_request)


def _primary_count(session, event_id) -> int:
    session.expire_all()
    return session.execute(
        select(func.count()).select_from(RangeAssignment).where(
            RangeAssignment.range_event_id == event_id, RangeAssignment.is_reserve.is_(False),
        )
    ).scalar_one()


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="C4: approve_assignment_request skips the per-date advisory lock, so it overruns capacity "
           "concurrently with add_range_assignment",
)
def test_request_approval_and_manual_add_cannot_exceed_capacity(race, admin_session, monkeypatch):
    event_id, request_id, admin_id, manual_id = _seed(admin_session, required_count=1)

    outcomes = _race_add_vs_approve(race, monkeypatch, event_id, request_id, admin_id, manual_id)

    for outcome in outcomes:
        if not outcome.ok and not isinstance(outcome.error, ranges_service.RangeValidationError):
            raise RuntimeError(f"request crashed: {outcome.error!r}") from outcome.error
    assert any(o.ok for o in outcomes), outcomes
    primaries = _primary_count(admin_session, event_id)
    assert primaries <= 1, f"required_count=1 but {primaries} primaries committed; outcomes={outcomes}"


def test_request_approval_and_manual_add_within_capacity_both_succeed(race, admin_session, monkeypatch):
    """Control: with two free slots both the manual add and the approval land."""
    event_id, request_id, admin_id, manual_id = _seed(admin_session, required_count=2)

    outcomes = _race_add_vs_approve(race, monkeypatch, event_id, request_id, admin_id, manual_id)

    assert all(o.ok for o in outcomes), outcomes
    assert _primary_count(admin_session, event_id) == 2
    admin_session.expire_all()
    assert admin_session.get(RangeAssignmentRequest, request_id).status == "approved"
