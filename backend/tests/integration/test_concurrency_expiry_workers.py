"""C7 — expiry worker overwrites a concurrent decision (audit inventory S4, E2).

``_expire_stale_requests`` (every uvicorn process, every 5 minutes) calls
``expire_started_swaps`` and ``expire_stale_exemption_requests``. Both SELECT
the still-open rows without a lock, then write ``status`` unconditionally by
primary key. A user decision that commits between that SELECT and the worker's
UPDATE is overwritten, while its side effects (cover overrides, granted
exemption) stay committed.

Schedule reproduced here (two independent sessions = worker process + HTTP request):
  1. the worker SELECTs the open request and parks right after the SELECT;
  2. the decision request locks the request (FOR UPDATE), applies it, commits;
  3. the worker resumes, writes the expired/cancelled status and commits.

Fixed (Task 3): after the unlocked candidate SELECT, both workers lock each
request with the decision paths' ``_lock_request`` (``FOR UPDATE``, fresh
read) and skip it unless it is still open/pending. In this schedule the worker
locks after the decision committed, sees ``applied``/``approved`` and leaves
it alone (returns 0).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyLocation,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    SoldierExemption,
    SwapRequest,
)
from app.services import exemption_requests as exemption_service
from app.services import swaps as swap_service
from tests.helpers import create_node, create_soldier


def _worker_vs_decision(race, *, worker_entity, worker_call, decision_call):
    worker_read = race.signal("worker read the open request")
    decision_done = race.signal("decision committed")

    def worker():
        s = race.session()

        def park():
            worker_read.set()
            decision_done.wait()

        race.pause_after_select(s, worker_entity, park)
        count = worker_call(s)
        s.commit()
        return count

    def decision():
        worker_read.wait()
        s = race.session()
        try:
            result = decision_call(s)
            s.commit()
            return result
        finally:
            decision_done.set()

    outcomes = race.run(worker, decision)
    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"racer crashed: {outcome.error!r}") from outcome.error
    return outcomes


def _seed_swap(session):
    node = create_node(session, level="unit", name="race-swap-expiry")
    requester = create_soldier(session, personal_number="race-swx-req", hierarchy_node_id=node.id)
    target = create_soldier(session, personal_number="race-swx-target", hierarchy_node_id=node.id)
    dt = DutyType(name="race-swx-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-swx-loc")
    session.add_all([dt, loc])
    session.flush()
    start = date.today() + timedelta(days=10)
    assignment = DutyAssignment(
        soldier_id=requester.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start, end_date=start + timedelta(days=1), status="published",
    )
    session.add(assignment)
    session.flush()
    req = swap_service.create_request(
        session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None, open_to_marketplace=False,
    )
    session.commit()
    return req.id, assignment.id, start, target.id


def test_swap_expiry_does_not_cancel_a_swap_applied_after_its_read(race, admin_session):
    request_id, assignment_id, start, target_id = _seed_swap(admin_session)
    # The worker runs "after the duty started"; the decision is a normal request.
    worker_now = datetime.combine(start, time(1, 0))

    outcomes = _worker_vs_decision(
        race,
        worker_entity=SwapRequest,
        worker_call=lambda s: swap_service.expire_started_swaps(s, now=worker_now),
        decision_call=lambda s: swap_service.approve_soldier_side(
            s, request_id=request_id, soldier_id=target_id, actor_id=target_id,
        ).status,
    )

    admin_session.expire_all()
    status = admin_session.get(SwapRequest, request_id).status
    overrides = admin_session.execute(
        select(func.count()).select_from(DutyDayOverride).where(DutyDayOverride.duty_assignment_id == assignment_id)
    ).scalar_one()
    assert (status, overrides > 0) in {("applied", True), ("cancelled", False)}, (
        f"worker cancelled {outcomes[0].value} request(s), decision returned {outcomes[1].value!r}; "
        f"final swap status={status!r} but {overrides} cover override(s) are committed"
    )
    assert (status, outcomes[0].value) == ("applied", 0)


def _seed_exemption(session):
    soldier = create_soldier(session, personal_number="race-exx-soldier")
    dm = create_soldier(session, personal_number="race-exx-admin", role="admin")
    et = ExemptionType(name="race-exx-type")
    session.add(et)
    session.flush()
    start = date.today() + timedelta(days=1)
    req = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, start_date=start, end_date=start + timedelta(days=5),
        reason="race", status="pending_duty_manager",
    )
    session.add(req)
    session.commit()
    return req.id, soldier.id, dm.id, req.end_date


def test_exemption_expiry_does_not_expire_a_request_approved_after_its_read(race, admin_session):
    request_id, soldier_id, dm_id, end_date = _seed_exemption(admin_session)
    worker_today = end_date + timedelta(days=1)

    outcomes = _worker_vs_decision(
        race,
        worker_entity=ExemptionRequest,
        worker_call=lambda s: exemption_service.expire_stale_exemption_requests(s, today=worker_today),
        decision_call=lambda s: exemption_service.approve_duty_manager_step(s, request_id, decided_by=dm_id).status,
    )

    admin_session.expire_all()
    status = admin_session.get(ExemptionRequest, request_id).status
    granted = admin_session.execute(
        select(func.count()).select_from(SoldierExemption).where(SoldierExemption.soldier_id == soldier_id)
    ).scalar_one()
    assert (status, granted > 0) in {("approved", True), ("expired", False)}, (
        f"worker expired {outcomes[0].value} request(s), decision returned {outcomes[1].value!r}; "
        f"final request status={status!r} but {granted} soldier_exemptions row(s) are committed"
    )
    assert (status, outcomes[0].value) == ("approved", 0)
