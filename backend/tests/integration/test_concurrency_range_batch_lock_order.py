"""C11 — deadlock in range ``assign_batch`` reconciliation lock order (audit inventory R2).

Range roster writers serialize per date with ``pg_advisory_xact_lock(ns, date)``.
``reconcile_future_range_assignments`` then removes each soldier's redundant
later assignments, taking the later dates' locks in ascending order *for that
soldier*. ``assign_batch`` reconciles soldier after soldier, so across the batch
the later-date locks are not ascending.

Schedule reproduced here (two independent sessions = two HTTP requests):
  1. the batch on D1 for [A, B] holds D1 and, reconciling A, D5 (A's later range);
  2. an ``add_range_assignment`` of C on D3 holds D3 and, reconciling C, waits for D5;
  3. the batch, reconciling B, waits for D3 (B's later range).
PostgreSQL aborts one request with ``DeadlockDetected`` (an unhandled 500).

Fixed (Task 4): before reconciling, ``assign_batch`` calls
``lock_reconciliation_target_dates``, which takes every later date the batch
may touch in ascending order (D3, then D5). The single add then blocks on D3,
the batch's wait for it times out, the batch commits, and the add runs after.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import DutyType, RangeAssignment, RangeEvent, RangeType, Soldier, SystemSetting
from app.services import range_reconciliation
from app.services import ranges as ranges_service
from tests.helpers import create_node, create_range_location, create_soldier

_D1, _D3, _D5 = (date.today() + timedelta(days=d) for d in (5, 8, 11))


def _seed(session):
    session.add(SystemSetting(key="mitvachim.enabled", value=True))
    node = create_node(session, level="branch", name="race-range-lo")
    session.add(DutyType(name="race-range-lo weapon", score_per_day=Decimal("1.00"),
                         requires_weapon=True, eligible_node_ids=[node.id]))
    admin = create_soldier(session, personal_number="race-rlo-admin", role="admin")
    a, b, c = (create_soldier(session, personal_number=f"race-rlo-{n}", hierarchy_node_id=node.id) for n in "abc")
    location = create_range_location(session, name="race-range-lo range")

    def event(range_type, day):
        e = RangeEvent(hierarchy_node_id=node.id, range_type=range_type, date=day,
                       range_location_id=location.id, required_count=2, reserve_count=0)
        session.add(e)
        session.flush()
        return e

    d1 = event(RangeType.live, _D1)
    d3 = event(RangeType.laser, _D3)
    d5 = event(RangeType.laser, _D5)
    # Later assignments the new coverage makes redundant (inserted directly so
    # seeding does not run reconciliation itself).
    session.add_all([
        RangeAssignment(range_event_id=d5.id, soldier_id=a.id),
        RangeAssignment(range_event_id=d3.id, soldier_id=b.id),
        RangeAssignment(range_event_id=d5.id, soldier_id=c.id),
    ])
    session.commit()
    return d1.id, d3.id, admin.id, a.id, b.id, c.id


def test_batch_reconciliation_and_single_add_do_not_deadlock(race, admin_session, monkeypatch):
    d1_id, d3_id, admin_id, a_id, b_id, c_id = _seed(admin_session)

    batch_holds_d5 = race.signal("batch holds the D5 lock")
    adder_holds_d3 = race.signal("single add holds the D3 lock")
    sessions: dict[str, object] = {}
    real_lock = ranges_service._acquire_range_assignment_date_lock

    def lock_then_sync(session, *, event_date):
        real_lock(session, event_date=event_date)
        if session is sessions.get("batch") and event_date == _D5:
            batch_holds_d5.set()
            adder_holds_d3.wait()
        elif session is sessions.get("add") and event_date == _D3:
            adder_holds_d3.set()

    # range_reconciliation imports the lock helper by name.
    monkeypatch.setattr(ranges_service, "_acquire_range_assignment_date_lock", lock_then_sync)
    monkeypatch.setattr(range_reconciliation, "_acquire_range_assignment_date_lock", lock_then_sync)

    def batch():
        s = sessions["batch"] = race.session()
        user = s.get(Soldier, admin_id)
        return ranges_service.assign_batch(
            s, event=s.get(RangeEvent, d1_id), primary_soldier_ids=[a_id, b_id],
            reserve_soldier_ids=[], user=user,
        )

    def add():
        batch_holds_d5.wait()
        s = sessions["add"] = race.session()
        user = s.get(Soldier, admin_id)
        return ranges_service.add_range_assignment(
            s, event=s.get(RangeEvent, d3_id), soldier_id=c_id, is_reserve=False, user=user,
        )

    outcomes = race.run(batch, add)

    admin_session.expire_all()
    rows = sorted(
        (str(event_date), str(soldier_id)) for event_date, soldier_id in admin_session.execute(
            select(RangeEvent.date, RangeAssignment.soldier_id).join(RangeEvent)
        )
    )
    batched, added = outcomes
    # Once serialized, the batch may refill B's vacated D3 slot with C, so the
    # later single add can fail with a domain error. A database error
    # (DeadlockDetected) is the defect.
    assert batched.ok and (added.ok or isinstance(added.error, ranges_service.RangeValidationError)), (
        f"outcomes={outcomes}; rows={rows}"
    )
    assert (str(_D1), str(a_id)) in rows and (str(_D1), str(b_id)) in rows
    assert any(row == (str(_D3), str(c_id)) for row in rows)
