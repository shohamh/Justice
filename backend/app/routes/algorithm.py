from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import (
    AlgorithmJob,
    AssignmentExplanation,
    DutyAssignment,
    DutyReserveLink,
    DutyShift,
    Soldier,
)
from app.db.session import get_session
from app.services.algorithm_bridge import run_algorithm_job
from app.services.assignments import cancel_assignment
from app.audit.writer import write_audit

router = APIRouter(prefix="/algorithm", tags=["algorithm"])


def _compute_candidate_rank(
    candidates: list[dict],
    soldier_id: str,
) -> tuple[int | None, int | None]:
    """Return (1-based rank, pool_size) for soldier among unblocked candidates sorted by pre_norm_score asc."""
    unblocked = [c for c in candidates if not c.get("blocked")]
    pool_size = len(unblocked)
    if pool_size == 0:
        return None, 0
    sorted_unblocked = sorted(
        unblocked,
        key=lambda c: c.get("pre_norm_score") if c.get("pre_norm_score") is not None else float("inf"),
    )
    for i, c in enumerate(sorted_unblocked):
        if c["soldier_id"] == soldier_id:
            return i + 1, pool_size
    return None, pool_size


# ── Pydantic schemas ──

class SolverSettingsIn(BaseModel):
    K: int = 8
    T: int = 7
    W: int = 14
    alpha: float = 1.0
    beta: float = 2.0
    time_limit_seconds: int = 30


class CreateJobRequest(BaseModel):
    shift_ids: list[uuid.UUID] = Field(min_length=1)
    mode: str = "shadow"
    settings: SolverSettingsIn = Field(default_factory=SolverSettingsIn)


class ProposalOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    reserve_assignment_id: uuid.UUID | None
    norm_score_before: float | None
    norm_score_after: float | None
    duty_shift_id: uuid.UUID | None = None
    candidate_rank: int | None = None
    candidate_pool_size: int | None = None


class JobOut(BaseModel):
    id: uuid.UUID
    status: str
    mode: str
    planning_start: date
    planning_end: date
    started_at: Any
    finished_at: Any
    error_message: str | None
    proposals: list[ProposalOut]
    solver_metrics: dict[str, Any]
    relaxed: list[str]


def _load_job(session: Session, job_id: uuid.UUID) -> AlgorithmJob:
    job = session.get(AlgorithmJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return job


def _load_assignment(session: Session, assignment_id: uuid.UUID) -> DutyAssignment:
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return a


def _proposals_for_job(session: Session, job: AlgorithmJob) -> list[ProposalOut]:
    """Load proposals created for this job, identified via the audit log."""
    if job.status != "done":
        return []

    from app.db.models import AuditLog

    # Find assignment IDs created for this specific job via audit log entries
    audit_rows = session.execute(
        select(AuditLog.entity_id).where(
            AuditLog.action == "algorithm.proposal.create",
            AuditLog.context["job_id"].astext == str(job.id),
        )
    ).scalars().all()

    assignment_ids = {eid for eid in audit_rows if eid is not None}
    if not assignment_ids:
        return []

    rows = (
        session.execute(
            select(DutyAssignment).where(DutyAssignment.id.in_(assignment_ids))
        )
        .scalars()
        .all()
    )
    reserve_links = (
        session.execute(
            select(DutyReserveLink).where(
                DutyReserveLink.primary_assignment_id.in_(assignment_ids)
            )
        )
        .scalars()
        .all()
    )
    reserve_map = {lk.primary_assignment_id: lk.reserve_assignment_id for lk in reserve_links}

    explanations = (
        session.execute(
            select(AssignmentExplanation).where(
                AssignmentExplanation.duty_assignment_id.in_(assignment_ids)
            )
        )
        .scalars()
        .all()
    )
    exp_map = {e.duty_assignment_id: e for e in explanations}

    proposals = []
    for a in rows:
        exp = exp_map.get(a.id)
        norm_before = None
        norm_after = None
        candidate_rank = None
        candidate_pool_size = None
        if exp:
            payload = exp.payload
            candidates = payload.get("candidates", [])
            for c in candidates:
                if c["soldier_id"] == str(a.soldier_id) and not c.get("blocked"):
                    norm_before = c.get("pre_norm_score")
                    norm_after = c.get("post_norm_score")
                    break
            candidate_rank, candidate_pool_size = _compute_candidate_rank(candidates, str(a.soldier_id))
        proposals.append(ProposalOut(
            assignment_id=a.id,
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            duty_location_id=a.duty_location_id,
            start_date=a.start_date,
            end_date=a.end_date,
            status=a.status,
            reserve_assignment_id=reserve_map.get(a.id),
            norm_score_before=norm_before,
            norm_score_after=norm_after,
            duty_shift_id=a.duty_shift_id,
            candidate_rank=candidate_rank,
            candidate_pool_size=candidate_pool_size,
        ))
    return proposals


def _explanation_response(
    session: Session, assignment: DutyAssignment, user: Soldier
) -> dict[str, Any]:
    """Build the explanation response dict, redacted for soldiers."""
    is_dm = user.role in ("duty_manager", "admin")
    is_assignee = assignment.soldier_id == user.id
    if not is_dm and not is_assignee:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    exp = session.execute(
        select(AssignmentExplanation).where(
            AssignmentExplanation.duty_assignment_id == assignment.id
        )
    ).scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    payload = exp.payload
    if is_dm:
        return payload

    # Soldier-redacted view
    blocked_count = sum(1 for c in payload.get("candidates", []) if c.get("blocked"))
    my_candidate = next(
        (c for c in payload.get("candidates", []) if c["soldier_id"] == str(user.id)),
        None,
    )
    return {
        "assigned": True,
        "norm_score_before": my_candidate.get("pre_norm_score") if my_candidate else None,
        "norm_score_after": my_candidate.get("post_norm_score") if my_candidate else None,
        "blocked_count": blocked_count,
        "tiebreaker_note": payload.get("tiebreaker_note"),
        "global_before": payload.get("global_before", {}),
        "global_after": payload.get("global_after", {}),
    }


# ── Endpoints ──

@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    body: CreateJobRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
    if body.mode not in ("shadow", "dm_reviewed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad_mode")
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    from app.services.shifts import get_shift_fill

    all_full = True
    for sid in body.shift_ids:
        shift = session.get(DutyShift, sid)
        if shift is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shift_not_found")
        fill = get_shift_fill(session, shift_id=sid)
        if fill and fill.fill_status != "full":
            all_full = False
    if all_full:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="all_shifts_full")

    shifts = [session.get(DutyShift, sid) for sid in body.shift_ids]
    planning_start = min(s.start_date for s in shifts if s)
    planning_end = max(s.end_date for s in shifts if s)

    job = AlgorithmJob(
        planning_start=planning_start,
        planning_end=planning_end,
        shift_ids=[str(sid) for sid in body.shift_ids],
        settings_json=body.settings.model_dump(),
        mode=body.mode,
        created_by=user.id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    background_tasks.add_task(run_algorithm_job, job.id, user.id)
    return {"id": str(job.id), "status": job.status}


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> JobOut:
    job = _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    proposals = _proposals_for_job(session, job)
    return JobOut(
        id=job.id,
        status=job.status,
        mode=job.mode,
        planning_start=job.planning_start,
        planning_end=job.planning_end,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
        proposals=proposals,
        solver_metrics={},
        relaxed=[],
    )


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def cancel_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    job = _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_cancellable")
    job.status = "failed"
    job.error_message = "cancelled_by_user"
    session.commit()


@router.post("/reset-published", status_code=status.HTTP_200_OK)
def reset_published_assignments(
    days_ahead: int = Query(ge=1),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    cutoff = date.today() + timedelta(days=days_ahead)
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "published",
            DutyAssignment.start_date > cutoff,
        )
    ).scalars().all()

    for a in assignments:
        cancel_assignment(session, assignment=a, reason="bulk_reset", actor_id=user.id)

    session.commit()
    return {"cancelled": len(assignments)}


@router.get("/jobs/{job_id}/explanations/{assignment_id}")
def get_explanation(
    job_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
    _load_job(session, job_id)
    a = _load_assignment(session, assignment_id)
    return _explanation_response(session, a, user)


@router.get("/explanations/{assignment_id}")
def get_explanation_direct(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
    """Direct explanation lookup by assignment_id (for soldier MyDutiesPage)."""
    a = _load_assignment(session, assignment_id)
    return _explanation_response(session, a, user)


@router.post("/jobs/{job_id}/proposals/{assignment_id}/accept", status_code=status.HTTP_200_OK)
def accept_proposal(
    job_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    _load_job(session, job_id)
    a = _load_assignment(session, assignment_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if a.status != "algorithm_draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_draft")
    a.status = "published"
    write_audit(
        session,
        actor_id=user.id,
        action="algorithm.proposal.accept",
        entity_type="duty_assignment",
        entity_id=a.id,
        before={"status": "algorithm_draft"},
        after={"status": "published"},
        context={"job_id": str(job_id)},
    )
    session.commit()
    return {"status": "published"}


@router.post("/jobs/{job_id}/proposals/{assignment_id}/reject", status_code=status.HTTP_200_OK)
def reject_proposal(
    job_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    _load_job(session, job_id)
    a = _load_assignment(session, assignment_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if a.status != "algorithm_draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_draft")
    a.status = "algorithm_rejected"
    write_audit(
        session,
        actor_id=user.id,
        action="algorithm.proposal.reject",
        entity_type="duty_assignment",
        entity_id=a.id,
        before={"status": "algorithm_draft"},
        after={"status": "algorithm_rejected"},
        context={"job_id": str(job_id)},
    )
    session.commit()
    return {"status": "algorithm_rejected"}
