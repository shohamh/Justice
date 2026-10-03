"""C8/J3 — single-item proposal accept vs reject lose updates.

``accept_proposal_direct`` / ``reject_proposal_direct`` (and the job-scoped
single-item routes) load the draft assignment with ``session.get``, check
``status == 'algorithm_draft'`` and write the new status by primary key. The
bulk routes use a conditional ``UPDATE ... WHERE status = 'algorithm_draft'``;
the single-item routes do not.

Schedule reproduced here (two independent sessions = two HTTP requests):
  1. the reject request loads the draft (status=algorithm_draft);
  2. the accept request publishes it (and refreshes the score projection) and commits;
  3. the reject request resumes, sets algorithm_rejected and commits.

Fixed (Task 3): the four single-item accept/reject routes use the same
conditional ``UPDATE ... WHERE status = 'algorithm_draft'`` as the bulk
routes. The late reject matches no row and gets 409 ``not_draft``.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.db.models import DutyAssignment, DutyLocation, DutyType, Soldier
from tests.helpers import create_soldier


def test_accept_and_reject_of_one_draft_cannot_both_succeed(race, admin_session):
    # Imported here, not at module level: app.routes.algorithm builds the shared
    # rate limiter with the Redis URL at import time, which must happen after
    # the Redis test-container fixture ran (see app/routes/tests/test_candidate_rank.py).
    from app.routes import algorithm as algorithm_routes

    admin = create_soldier(admin_session, personal_number="race-prop-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="race-prop-soldier")
    dt = DutyType(name="race-prop-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-prop-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    start = date.today() + timedelta(days=15)
    draft = DutyAssignment(soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
                           start_date=start, end_date=start + timedelta(days=1), status="algorithm_draft")
    admin_session.add(draft)
    admin_session.commit()
    draft_id, admin_id = draft.id, admin.id

    late, early = race.stale_write(
        read=lambda s: s.get(DutyAssignment, draft_id),
        write=lambda s, _row: algorithm_routes.reject_proposal_direct(
            assignment_id=draft_id, session=s, user=s.get(Soldier, admin_id),
        )["status"],
        decide=lambda s: algorithm_routes.accept_proposal_direct(
            assignment_id=draft_id, session=s, user=s.get(Soldier, admin_id),
        )["status"],
    )

    for outcome in (late, early):
        if not outcome.ok and not isinstance(outcome.error, HTTPException):
            raise RuntimeError(f"route crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    final_status = admin_session.get(DutyAssignment, draft_id).status
    assert (early.ok, late.ok) == (True, False), (
        f"accept={early!r}, reject={late!r}; final assignment status={final_status!r}"
    )
    assert final_status == "published"
    assert (late.error.status_code, late.error.detail) == (409, "not_draft")


def _stale_draft_over_a_manual_assignment(race, admin_session, tag):
    """J2 schedule: the solver snapshots the soldier as free; while it solves,
    a manager assigns the soldier manually (create_assignment, committed); the
    runner then persists its draft from the stale snapshot (persist_results
    does not re-check overlap). Returns ids for the accept step."""
    from app.db.models import AlgorithmJob
    from app.services import assignments as assignments_service

    admin = create_soldier(admin_session, personal_number=f"race-j2-{tag}-admin", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"race-j2-{tag}-soldier")
    dt = DutyType(name=f"race-j2-{tag}-type", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"race-j2-{tag}-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    start = date.today() + timedelta(days=15)
    job = AlgorithmJob(
        planning_start=start, planning_end=start, shift_ids=[], settings_json={}, mode="shadow",
        created_by=admin.id, status="done",
    )
    admin_session.add(job)
    admin_session.commit()
    ids = {"admin": admin.id, "soldier": soldier.id, "dt": dt.id, "loc": loc.id, "job": job.id}

    manager = race.session()
    assignments_service.create_assignment(
        manager, soldier_id=ids["soldier"], duty_type_id=ids["dt"], duty_location_id=ids["loc"],
        start_date=start, end_date=start + timedelta(days=1), actor_id=ids["admin"],
    )
    manager.commit()

    runner = race.session()
    draft = DutyAssignment(
        soldier_id=ids["soldier"], duty_type_id=ids["dt"], duty_location_id=ids["loc"], start_date=start,
        end_date=start + timedelta(days=1), status="algorithm_draft", algorithm_job_id=ids["job"],
    )
    runner.add(draft)
    runner.commit()
    ids["draft"] = draft.id
    return ids


def _published_count(admin_session, soldier_id):
    from sqlalchemy import func, select

    admin_session.expire_all()
    return admin_session.execute(
        select(func.count()).select_from(DutyAssignment).where(
            DutyAssignment.soldier_id == soldier_id, DutyAssignment.status == "published",
        )
    ).scalar_one()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="J2: accept publishes a draft over a manual assignment")
def test_accepting_a_stale_draft_cannot_double_book_the_soldier(race, admin_session):
    from app.routes import algorithm as algorithm_routes

    ids = _stale_draft_over_a_manual_assignment(race, admin_session, "single")
    s = race.session()
    error = None
    try:
        algorithm_routes.accept_proposal_direct(assignment_id=ids["draft"], session=s, user=s.get(Soldier, ids["admin"]))
    except HTTPException as exc:
        error = (exc.status_code, exc.detail)
        s.rollback()

    published = _published_count(admin_session, ids["soldier"])
    assert published == 1, f"soldier has {published} overlapping published duties"
    assert error == (409, "overlap")
    assert admin_session.get(DutyAssignment, ids["draft"]).status == "algorithm_draft"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="J2: bulk accept publishes a draft over a manual assignment")
def test_bulk_accept_skips_a_stale_draft_that_would_double_book(race, admin_session):
    from app.routes import algorithm as algorithm_routes

    ids = _stale_draft_over_a_manual_assignment(race, admin_session, "bulk")
    s = race.session()
    result = algorithm_routes.bulk_accept_proposals(
        job_id=ids["job"], body=algorithm_routes.BulkAcceptRequest(assignment_ids=[ids["draft"]]),
        session=s, user=s.get(Soldier, ids["admin"]),
    )

    published = _published_count(admin_session, ids["soldier"])
    assert published == 1, f"soldier has {published} overlapping published duties"
    assert result == {"accepted": 0}
    assert admin_session.get(DutyAssignment, ids["draft"]).status == "algorithm_draft"
