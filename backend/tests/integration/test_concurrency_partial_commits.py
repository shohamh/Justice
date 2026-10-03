"""C18 — ``recheck_assignments`` commits in the middle of a caller's transaction (audit inventory J6).

``duty_eligibility_watch.recheck_assignments(session, ids)`` defaults to
``commit=True`` and calls ``session.commit()`` whenever it finds a published
assignment to recheck. Callers that run it in the middle of a larger unit of
work therefore commit half of it:

* ``POST /algorithm/jobs/{id}/proposals/{aid}/accept`` and ``.../bulk-accept``
  publish the draft, recheck, then refresh the score projection and the job
  status. If a later step fails, the publish is already committed;
* ``range_excusal.decide_primary_excusal`` (and the other excusal paths)
  recheck before notifying / reconciling. The mid-way commit also releases the
  per-date advisory lock and the request row lock that serialize excusal
  decisions (C8/R5), so the rest of the decision runs unserialized.

Failure-injection schedule: make the step right after the recheck raise, roll
back as the request handler would, and check that nothing was committed.

Fixed (Task 4): these callers pass ``commit=False`` and commit once at the end
of their own unit of work (as ``recheck_soldier_assignments`` already did). The
same change was applied to ``ranges.mark_attendance``. Callers whose recheck is
the last step after their own commit (the duty-config and settings routes, the
eligibility worker) keep the default.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import (
    AlgorithmJob,
    DutyAssignment,
    DutyLocation,
    DutyType,
    RangeAssignment,
    RangeEvent,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeType,
    Soldier,
    SystemSetting,
)
from tests.helpers import create_node, create_range_location, create_soldier


class _Injected(Exception):
    pass


def _boom(*_args, **_kwargs):
    raise _Injected("injected failure after recheck_assignments")


def _draft(session, tag):
    admin = create_soldier(session, personal_number=f"pc-{tag}-admin", role="admin")
    soldier = create_soldier(session, personal_number=f"pc-{tag}-soldier")
    dt = DutyType(name=f"pc-{tag}-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"pc-{tag}-loc")
    session.add_all([dt, loc])
    session.flush()
    start = date.today() + timedelta(days=15)
    job = AlgorithmJob(planning_start=start, planning_end=start, shift_ids=[], settings_json={},
                       mode="shadow", created_by=admin.id, status="done")
    session.add(job)
    session.flush()
    draft = DutyAssignment(soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
                           start_date=start, end_date=start + timedelta(days=1), status="algorithm_draft",
                           algorithm_job_id=job.id)
    session.add(draft)
    session.commit()
    return job.id, draft.id, admin.id


def _status_after_failure(admin_session, session, call, assignment_id):
    with pytest.raises(_Injected):
        call()
    session.rollback()
    admin_session.expire_all()
    return admin_session.get(DutyAssignment, assignment_id).status


def test_failed_proposal_accept_leaves_the_draft_unpublished(admin_session, app_session, monkeypatch):
    from app.routes import algorithm as algorithm_routes

    job_id, draft_id, admin_id = _draft(admin_session, "one")
    monkeypatch.setattr(algorithm_routes, "refresh_projection_for_assignment_change", _boom)

    status = _status_after_failure(admin_session, app_session, lambda: algorithm_routes.accept_proposal(
        job_id=job_id, assignment_id=draft_id, session=app_session, user=app_session.get(Soldier, admin_id),
    ), draft_id)

    assert status == "algorithm_draft", f"the failed accept left the proposal {status!r}"


def test_failed_bulk_accept_leaves_the_drafts_unpublished(admin_session, app_session, monkeypatch):
    from app.routes import algorithm as algorithm_routes

    job_id, draft_id, admin_id = _draft(admin_session, "bulk")
    monkeypatch.setattr(algorithm_routes, "refresh_projections_for_assignments_bulk", _boom)

    status = _status_after_failure(admin_session, app_session, lambda: algorithm_routes.bulk_accept_proposals(
        job_id=job_id, body=algorithm_routes.BulkAcceptRequest(assignment_ids=[draft_id]),
        session=app_session, user=app_session.get(Soldier, admin_id),
    ), draft_id)

    assert status == "algorithm_draft", f"the failed bulk accept left the proposal {status!r}"


def test_failed_excusal_approval_rolls_back_completely(admin_session, app_session, monkeypatch):
    from app.services import range_excusal as excusal_service

    admin_session.add(SystemSetting(key="mitvachim.enabled", value=True))
    node = create_node(admin_session, level="branch", name="pc-excusal")
    admin_session.add(DutyType(name="pc-excusal weapon", score_per_day=Decimal("1.00"),
                               requires_weapon=True, eligible_node_ids=[node.id]))
    admin = create_soldier(admin_session, personal_number="pc-exc-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="pc-exc-p", hierarchy_node_id=node.id)
    dt = DutyType(name="pc-exc-duty", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="pc-exc-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    # A published duty gives recheck_assignments something to recheck (and so
    # to commit).
    duty_start = date.today() + timedelta(days=30)
    admin_session.add(DutyAssignment(soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
                                     start_date=duty_start, end_date=duty_start + timedelta(days=1),
                                     status="published"))
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type=RangeType.laser, date=date.today() + timedelta(days=14),
        range_location_id=create_range_location(admin_session, name="pc-excusal range").id,
        required_count=1, reserve_count=0,
    )
    admin_session.add(event)
    admin_session.flush()
    primary = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id, is_reserve=False)
    admin_session.add(primary)
    admin_session.flush()
    request = RangeExcusalRequest(range_assignment_id=primary.id, range_event_id=event.id,
                                  requested_by=soldier.id, reason="sick", status=RangeExcusalStatus.pending)
    admin_session.add(request)
    admin_session.commit()
    request_id, primary_id = request.id, primary.id

    # The approve path with no reserve to promote notifies the duty managers
    # right after rechecking; make that step fail.
    monkeypatch.setattr(excusal_service, "notify_duty_managers_in_scope", _boom)
    with pytest.raises(_Injected):
        excusal_service.decide_primary_excusal(
            app_session, request=app_session.get(RangeExcusalRequest, request_id), approve=True,
            decided_by=admin.id,
        )
    app_session.rollback()

    admin_session.expire_all()
    status = admin_session.get(RangeExcusalRequest, request_id).status
    still_assigned = admin_session.get(RangeAssignment, primary_id) is not None
    assert (status, still_assigned) == (RangeExcusalStatus.pending, True), (
        f"the failed approval committed status={status!r}, primary assignment kept={still_assigned}"
    )
