"""C3 — shift assign-batch capacity overrun (audit inventory A2).

``POST /shifts/{id}/assign-batch`` counts the shift's active primaries with an
unlocked SELECT, compares against ``required_count``, then creates the
assignments. Nothing locks the ``duty_shifts`` row, and ``create_assignment``
only locks the *soldier*, so two batches for different soldiers never conflict.

Schedule reproduced here (two independent sessions = two HTTP requests):
  1. request A and request B each count 0 primaries on a required_count=1 shift;
  2. both meet at a rendezvous before their first ``create_assignment``;
  3. both insert a primary and commit.
"""
from __future__ import annotations

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


def _seed(session, *, required_count: int):
    node = create_node(session, level="branch", name="race-batch")
    admin = create_soldier(session, personal_number="race-batch-admin", role="admin")
    s1 = create_soldier(session, personal_number="race-batch-s1", hierarchy_node_id=node.id)
    s2 = create_soldier(session, personal_number="race-batch-s2", hierarchy_node_id=node.id)
    dt = DutyType(name="race-batch-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-batch-loc")
    session.add_all([dt, loc])
    session.flush()
    start = date.today() + timedelta(days=20)
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id, start_date=start,
                      end_date=start + timedelta(days=1), required_count=required_count,
                      reserve_count_override=0)
    session.add(shift)
    # Pre-create the quarter's score-projection total row. Two first-ever
    # projections for a quarter otherwise both INSERT it and one request dies on
    # score_projection_quarter_total_pkey (a separate projection race recorded in
    # the audit report, not the capacity race under test here).
    session.add(ScoreProjectionQuarterTotal(
        quarter_start=date(start.year, (start.month - 1) // 3 * 3 + 1, 1), projection_version="1",
        raw_day_count=0, effective_weighted_days=Decimal("0"), duty_score=Decimal("0"),
        adjustment_score=Decimal("0"), total_score=Decimal("0"),
    ))
    session.commit()
    return shift.id, admin.id, s1.id, s2.id


def _race_two_batches(race, monkeypatch, shift_id, admin_id, s1_id, s2_id):
    # Imported lazily so route-module import side effects (shared rate limiter
    # bound to the Redis URL) run after the Redis test-container fixture.
    from app.routes import shifts as shifts_routes

    after_capacity_check = race.rendezvous(2, "both requests passed the capacity check")
    real_create = assignments_service.create_assignment

    def create_after_rendezvous(session, **kwargs):
        after_capacity_check.wait()
        return real_create(session, **kwargs)

    monkeypatch.setattr(assignments_service, "create_assignment", create_after_rendezvous)

    def request(soldier_id):
        def _call():
            s = race.session()
            user = s.get(Soldier, admin_id)
            body = shifts_routes.BatchAssignRequest(primaries=[soldier_id], reserves=[])
            return shifts_routes.assign_batch(shift_id=shift_id, body=body, session=s, user=user)
        return _call

    return race.run(request(s1_id), request(s2_id))


def _active_primaries(session, shift_id) -> int:
    session.expire_all()
    return session.execute(
        select(func.count()).select_from(DutyAssignment).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.is_reserve.is_(False),
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).scalar_one()


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="C3: two concurrent assign-batch requests both pass the unlocked primary-capacity count",
)
def test_concurrent_batches_cannot_exceed_required_count(race, admin_session, monkeypatch):
    shift_id, admin_id, s1_id, s2_id = _seed(admin_session, required_count=1)

    outcomes = _race_two_batches(race, monkeypatch, shift_id, admin_id, s1_id, s2_id)

    from fastapi import HTTPException
    for outcome in outcomes:
        if not outcome.ok and not isinstance(outcome.error, HTTPException):
            raise RuntimeError(f"request crashed: {outcome.error!r}") from outcome.error
    primaries = _active_primaries(admin_session, shift_id)
    assert primaries <= 1, f"required_count=1 but {primaries} primaries were committed; outcomes={outcomes}"
    assert sum(o.ok for o in outcomes) == 1


def test_concurrent_batches_within_capacity_both_succeed(race, admin_session, monkeypatch):
    """Control: with room for both soldiers, both concurrent batches succeed."""
    shift_id, admin_id, s1_id, s2_id = _seed(admin_session, required_count=2)

    outcomes = _race_two_batches(race, monkeypatch, shift_id, admin_id, s1_id, s2_id)

    assert all(o.ok for o in outcomes), outcomes
    assert _active_primaries(admin_session, shift_id) == 2
