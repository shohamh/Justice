"""C10 — deadlock between two shift assign-batches (audit inventory A3).

``POST /shifts/{id}/assign-batch`` locks the shift row and then calls
``create_assignment`` once per soldier, in request-body order. Each call locks
its soldier (``FOR UPDATE``) and holds it until the batch commits. Two batches
for *different* shifts do not share the shift lock, so a batch [S1, S2] and a
batch [S2, S1] take the same soldier rows in opposite order.

Schedule reproduced here (two independent sessions = two HTTP requests):
  1. batch X (shift X, [S1, S2]) locks S1 and batch Y (shift Y, [S2, S1]) locks S2;
  2. both meet at a rendezvous after their first ``create_assignment``;
  3. X waits for S2 and Y waits for S1.
PostgreSQL aborts one batch with ``DeadlockDetected`` (an unhandled 500).
"""
from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    ScoreProjectionQuarterTotal,
    Soldier,
)
from app.services import assignments as assignments_service
from tests.helpers import create_node, create_soldier


def _quarter_start(d: date) -> date:
    return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


def _seed(session):
    node = create_node(session, level="branch", name="race-batch-lo")
    admin = create_soldier(session, personal_number="race-batch-lo-admin", role="admin")
    s1 = create_soldier(session, personal_number="race-batch-lo-s1", hierarchy_node_id=node.id)
    s2 = create_soldier(session, personal_number="race-batch-lo-s2", hierarchy_node_id=node.id)
    dt = DutyType(name="race-batch-lo-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-batch-lo-loc")
    session.add_all([dt, loc])
    session.flush()
    shift_ids = []
    for offset in (20, 40):
        start = date.today() + timedelta(days=offset)
        shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id, start_date=start,
                          end_date=start + timedelta(days=1), required_count=2, reserve_count_override=0)
        session.add(shift)
        session.flush()
        shift_ids.append(shift.id)
    # Pre-create the quarters' score-projection totals so the first-insert race
    # (O1, tested separately) does not mask the lock-order race under test.
    for quarter in {_quarter_start(date.today() + timedelta(days=o)) for o in (20, 40)}:
        session.add(ScoreProjectionQuarterTotal(
            quarter_start=quarter, projection_version="1", raw_day_count=0,
            effective_weighted_days=Decimal("0"), duty_score=Decimal("0"),
            adjustment_score=Decimal("0"), total_score=Decimal("0"),
        ))
    session.commit()
    return shift_ids, admin.id, s1.id, s2.id


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="C10: assign-batch locks soldiers in request-body order")
def test_batches_with_opposite_soldier_order_do_not_deadlock(race, admin_session, monkeypatch):
    from app.routes import shifts as shifts_routes

    (shift_x, shift_y), admin_id, s1_id, s2_id = _seed(admin_session)

    after_first_soldier = race.rendezvous(2, "each batch locked its first soldier")
    calls = threading.local()
    real_create = assignments_service.create_assignment

    def create_then_wait(session, **kwargs):
        result = real_create(session, **kwargs)
        calls.count = getattr(calls, "count", 0) + 1
        if calls.count == 1:
            after_first_soldier.wait()
        return result

    monkeypatch.setattr(assignments_service, "create_assignment", create_then_wait)

    def batch(shift_id, primaries):
        def _call():
            s = race.session()
            user = s.get(Soldier, admin_id)
            body = shifts_routes.BatchAssignRequest(primaries=primaries, reserves=[])
            return shifts_routes.assign_batch(shift_id=shift_id, body=body, session=s, user=user)
        return _call

    outcomes = race.run(batch(shift_x, [s1_id, s2_id]), batch(shift_y, [s2_id, s1_id]))

    admin_session.expire_all()
    committed = admin_session.execute(
        select(func.count()).select_from(DutyAssignment).where(DutyAssignment.duty_shift_id.in_([shift_x, shift_y]))
    ).scalar_one()
    assert all(o.ok for o in outcomes), f"outcomes={outcomes}; committed assignments={committed}"
    assert committed == 4
