import json as _json
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.rate_limit import limiter
from app.db.models import (
    AlgorithmJob,
    AssignmentExplanation,
    AuditLog,
    DutyAssignment,
    DutyReserveLink,
    DutyShift,
    DutyType,
    Soldier,
)
from app.db.session import get_session
from app.services.algorithm_bridge import run_algorithm_job
from app.audit.writer import write_audit

router = APIRouter(prefix="/algorithm", tags=["algorithm"])


def _compute_candidate_rank(
    candidates: list[dict],
    soldier_id: str,
    *,
    payload: dict | None = None,
) -> tuple[int | None, int | None]:
    """Return (1-based rank, pool_size) for soldier among unblocked candidates sorted by pre_norm_score asc.

    Uses pre-computed pool_size/assigned_rank from payload when available (new records).
    Falls back to scanning candidates for old records that predate the truncation change.
    """
    if payload is not None and payload.get("pool_size") is not None:
        if payload.get("assigned_soldier_id") == soldier_id:
            return payload.get("assigned_rank"), payload["pool_size"]

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
    T: int = 8
    Wt: int = 14
    R: int = 15
    Wr: int = 28
    alpha: float = 1.0
    time_limit_seconds: int = Field(default=30, ge=5, le=120)


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
    batch_index: int | None = None


class JobOut(BaseModel):
    id: uuid.UUID
    status: str
    mode: str
    planning_start: date
    planning_end: date
    started_at: Any
    finished_at: Any
    error_message: str | None
    progress_message: str | None
    proposals: list[ProposalOut]
    solver_metrics: dict[str, Any]
    relaxed: list[str]
    reasons: list[str]
    batch_results: list[dict] = Field(default_factory=list)
    result_metadata: dict[str, Any] | None = None


class JobSummaryOut(BaseModel):
    id: uuid.UUID
    status: str
    mode: str
    planning_start: date
    planning_end: date
    shift_count: int
    created_at: Any
    started_at: Any
    finished_at: Any
    error_message: str | None
    total_duties: int = 0
    assigned_duties: int = 0


class JobListOut(BaseModel):
    items: list[JobSummaryOut]
    total: int


class AlgorithmDefaultsOut(BaseModel):
    T: int
    Wt: int
    R: int
    Wr: int


class DraftPreviewItem(BaseModel):
    assignment_id: uuid.UUID
    soldier_name: str
    duty_type_name: str
    start_date: date
    end_date: date


class DraftsPreviewOut(BaseModel):
    count: int
    items: list[DraftPreviewItem]


def _parse_failure(error_message: str | None) -> tuple[list[str], list[str]]:
    """Parse the JSON stored in error_message for failed jobs."""
    if not error_message:
        return [], []
    try:
        data = _json.loads(error_message)
        return data.get("relaxed", []), data.get("reasons", [])
    except (ValueError, TypeError):
        return [], []


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


def _assignment_ids_for_job(session: Session, job_id: uuid.UUID) -> list[uuid.UUID]:
    rows = session.execute(
        select(AuditLog.entity_id).where(
            AuditLog.action == "algorithm.proposal.create",
            AuditLog.context["job_id"].astext == str(job_id),
        )
    ).scalars().all()
    return [eid for eid in rows if eid is not None]


def _maybe_publish_job(session: Session, job_id: uuid.UUID) -> None:
    """Set job status to 'published' when no algorithm_draft proposals remain."""
    from sqlalchemy import func
    assignment_ids = _assignment_ids_for_job(session, job_id)
    if not assignment_ids:
        return
    remaining = session.execute(
        select(func.count()).select_from(DutyAssignment).where(
            DutyAssignment.id.in_(assignment_ids),
            DutyAssignment.status == "algorithm_draft",
        )
    ).scalar_one()
    if remaining == 0:
        job = session.get(AlgorithmJob, job_id)
        if job and job.status == "done":
            job.status = "published"


def _job_id_for_assignment(session: Session, assignment_id: uuid.UUID) -> uuid.UUID | None:
    row = session.execute(
        select(AuditLog.context["job_id"].astext).where(
            AuditLog.action == "algorithm.proposal.create",
            AuditLog.entity_id == assignment_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        return uuid.UUID(row)
    except (ValueError, AttributeError):
        return None


def _proposals_for_job(session: Session, job: AlgorithmJob) -> list[ProposalOut]:
    """Load proposals created for this job."""
    if job.status not in ("done", "published"):
        return []

    # Fast path: new jobs have algorithm_job_id set directly on assignments.
    fast_rows = (
        session.execute(
            select(DutyAssignment).where(DutyAssignment.algorithm_job_id == job.id)
        )
        .scalars()
        .all()
    )

    if fast_rows:
        assignment_ids = {a.id for a in fast_rows}
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
        return [
            ProposalOut(
                assignment_id=a.id,
                soldier_id=a.soldier_id,
                duty_type_id=a.duty_type_id,
                duty_location_id=a.duty_location_id,
                start_date=a.start_date,
                end_date=a.end_date,
                status=a.status,
                reserve_assignment_id=reserve_map.get(a.id),
                norm_score_before=a.norm_score_before,
                norm_score_after=a.norm_score_after,
                duty_shift_id=a.duty_shift_id,
                candidate_rank=a.candidate_rank,
                candidate_pool_size=a.candidate_pool_size,
                batch_index=a.batch_index,
            )
            for a in fast_rows
        ]

    # Fallback: old jobs without algorithm_job_id — audit-log path.
    from app.db.models import AuditLog

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
            candidate_rank, candidate_pool_size = _compute_candidate_rank(
                candidates, str(a.soldier_id), payload=payload
            )
        proposals.append(
            ProposalOut(
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
                batch_index=a.batch_index,
            )
        )
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

    # Build context block included in every response variant
    assignee = session.get(Soldier, assignment.soldier_id)
    duty_type = session.get(DutyType, assignment.duty_type_id)
    assignment_context = {
        "soldier_name": assignee.full_name if assignee else str(assignment.soldier_id)[:8],
        "duty_type_name": duty_type.name if duty_type else str(assignment.duty_type_id)[:8],
        "start_date": assignment.start_date.isoformat(),
        "end_date": assignment.end_date.isoformat() if assignment.end_date else assignment.start_date.isoformat(),
    }

    payload = exp.payload
    if is_dm:
        return {**payload, "assignment_context": assignment_context}

    # Soldier-redacted view
    candidates = payload.get("candidates", [])
    # Use pre-computed aggregates when available (new records); fall back to counting
    # the truncated candidate list for old records that predate the truncation change.
    blocked_count = payload.get("blocked_count") if payload.get("blocked_count") is not None else sum(1 for c in candidates if c.get("blocked"))
    my_candidate = next(
        (c for c in candidates if c["soldier_id"] == str(user.id)),
        None,
    )

    _CONSTRAINT_LABELS_HE: dict[str, str] = {
        "exemption": "פטור",
        "personal_constraint": "אילוץ אישי",
        "overlap": "חפיפה",
    }

    def _score(c: dict) -> float | None:
        # Support both new key (pre_norm_score) and old key (pre_effort_score) for stored records
        v = c.get("pre_norm_score")
        if v is None:
            v = c.get("pre_effort_score")
        return v

    # Build enriched soldier view for the redesigned explanation modal
    eligible = [c for c in candidates if not c.get("blocked")]
    eligible_sorted = sorted(eligible, key=lambda c: (_score(c) or 0))
    eligible_count = payload.get("pool_size") if payload.get("pool_size") is not None else len(eligible)
    my_id = str(user.id)
    soldier_rank = payload.get("assigned_rank") if payload.get("assigned_rank") is not None else next(
        (i + 1 for i, c in enumerate(eligible_sorted) if c["soldier_id"] == my_id),
        1,
    )
    ranked_candidates = [
        {
            "soldier_id": c["soldier_id"],
            "full_name": c.get("soldier_name") or c["soldier_id"][:8],
            "score": _score(c),
            "reason_excluded": None,
        }
        for c in eligible_sorted
        if c["soldier_id"] != my_id
    ][:5]
    for c in candidates:
        if c.get("blocked") and len(ranked_candidates) < 5:
            constraints = c.get("blocking_constraints", [])
            reason = ", ".join(_CONSTRAINT_LABELS_HE.get(k, k) for k in constraints) or "חסום"
            ranked_candidates.append({
                "soldier_id": c["soldier_id"],
                "full_name": c.get("soldier_name") or c["soldier_id"][:8],
                "score": _score(c),
                "reason_excluded": reason,
            })

    my_score = _score(my_candidate) if my_candidate else None
    return {
        "assigned": True,
        "norm_score_before": my_score,
        "norm_score_after": my_candidate.get("post_norm_score") if my_candidate else None,
        "blocked_count": blocked_count,
        "tiebreaker_note": payload.get("tiebreaker_note"),
        "global_before": payload.get("global_before", {}),
        "global_after": payload.get("global_after", {}),
        # Enriched fields for the redesigned explanation modal
        "score_at_assignment": my_score,
        "eligible_count": eligible_count,
        "soldier_rank": soldier_rank,
        "constraint_count": len(my_candidate.get("blocking_constraints", [])) if my_candidate else 0,
        "my_constraints": my_candidate.get("blocking_constraints", []) if my_candidate else [],
        "ranked_candidates": ranked_candidates,
        "assignment_context": assignment_context,
    }


# ── Endpoints ──

@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute")
def create_job(
    body: CreateJobRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, Any]:
    if body.mode not in ("shadow", "dm_reviewed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad_mode")
    if body.settings.T > body.settings.R:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="t_exceeds_r")
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    from app.services.shifts import get_shift_fill

    shifts_by_id = {
        s.id: s
        for s in session.execute(
            select(DutyShift).where(DutyShift.id.in_(body.shift_ids))
        ).scalars().all()
    }
    for sid in body.shift_ids:
        if sid not in shifts_by_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="shift_not_found")

    all_full = all(
        (fill := get_shift_fill(session, shift_id=sid)) is None or fill.fill_status == "full"
        for sid in body.shift_ids
    )
    if all_full:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="all_shifts_full")

    shifts = list(shifts_by_id.values())
    planning_start = min(s.start_date for s in shifts)
    planning_end = max(s.end_date for s in shifts)

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


@router.get("/defaults", response_model=AlgorithmDefaultsOut)
def get_algorithm_defaults(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AlgorithmDefaultsOut:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    from app.services.algorithm_bridge import resolve_solver_settings
    s = resolve_solver_settings(session, {})
    return AlgorithmDefaultsOut(T=s.T, Wt=s.Wt, R=s.R, Wr=s.Wr)


@router.get("/jobs", response_model=JobListOut)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> JobListOut:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    from sqlalchemy import func

    total = session.execute(
        select(func.count()).select_from(AlgorithmJob).where(AlgorithmJob.created_by == user.id)
    ).scalar_one()

    jobs = session.execute(
        select(AlgorithmJob)
        .where(AlgorithmJob.created_by == user.id)
        .order_by(AlgorithmJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return JobListOut(
        items=[
            JobSummaryOut(
                id=j.id,
                status=j.status,
                mode=j.mode,
                planning_start=j.planning_start,
                planning_end=j.planning_end,
                shift_count=len(j.shift_ids),
                created_at=j.created_at,
                started_at=j.started_at,
                finished_at=j.finished_at,
                error_message=j.error_message,
                total_duties=j.total_duties,
                assigned_duties=j.assigned_duties,
            )
            for j in jobs
        ],
        total=total,
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> JobOut:
    job = _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    proposals = _proposals_for_job(session, job)
    relaxed, reasons = _parse_failure(job.error_message)
    meta = job.result_metadata or {}
    return JobOut(
        id=job.id,
        status=job.status,
        mode=job.mode,
        planning_start=job.planning_start,
        planning_end=job.planning_end,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
        progress_message=job.progress_message,
        proposals=proposals,
        solver_metrics=meta.get("solver_metrics") or {},
        relaxed=relaxed,
        reasons=reasons,
        batch_results=job.batch_results or [],
        result_metadata=job.result_metadata,
    )


@router.get("/jobs/{job_id}/export-inputs")
def export_job_inputs(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Any:
    """Return a JSON dump of solver inputs for this job, suitable for offline replay."""
    from fastapi.responses import JSONResponse
    from app.services.algorithm_bridge import export_solver_inputs
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    job = _load_job(session, job_id)
    data = export_solver_inputs(job, session)
    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f'attachment; filename="solver_dump_{job_id}.json"',
        },
    )


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def cancel_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    from datetime import datetime, timezone
    job = _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_cancellable")
    job.status = "failed"
    job.error_message = "cancelled_by_user"
    job.finished_at = datetime.now(tz=timezone.utc)
    session.commit()

    from app.services.algorithm_bridge import _cancel_events
    event = _cancel_events.get(str(job_id))
    if event:
        event.set()


@router.get("/drafts-preview", response_model=DraftsPreviewOut)
def get_drafts_preview(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> DraftsPreviewOut:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    today = date.today()
    rows = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "algorithm_draft",
            DutyAssignment.start_date >= today,
        )
    ).scalars().all()

    soldier_ids = {a.soldier_id for a in rows}
    dtype_ids = {a.duty_type_id for a in rows}

    soldiers = {s.id: s for s in session.execute(
        select(Soldier).where(Soldier.id.in_(soldier_ids))
    ).scalars().all()}
    duty_types = {d.id: d for d in session.execute(
        select(DutyType).where(DutyType.id.in_(dtype_ids))
    ).scalars().all()}

    items = []
    for a in rows:
        soldier = soldiers.get(a.soldier_id)
        duty_type = duty_types.get(a.duty_type_id)
        items.append(DraftPreviewItem(
            assignment_id=a.id,
            soldier_name=soldier.full_name if soldier else str(a.soldier_id),
            duty_type_name=duty_type.name if duty_type else str(a.duty_type_id),
            start_date=a.start_date,
            end_date=a.end_date,
        ))

    return DraftsPreviewOut(count=len(items), items=items)


@router.post("/reset-published", status_code=status.HTTP_200_OK)
def reset_published_assignments(
    days_ahead: int = Query(ge=0),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    cutoff = date.today() + timedelta(days=days_ahead)
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "published",
            DutyAssignment.start_date >= cutoff,
        )
    ).scalars().all()

    # Bulk admin reset — direct mutation without per-soldier notifications (same pattern as reset-drafts).
    for a in assignments:
        a.status = "cancelled"
        write_audit(
            session,
            actor_id=user.id,
            action="assignment.bulk_cancel",
            entity_type="duty_assignment",
            entity_id=a.id,
            before={"status": "published"},
            after={"status": "cancelled"},
            context={"days_ahead": days_ahead},
        )

    session.commit()
    return {"cancelled": len(assignments)}


@router.post("/reset-drafts", status_code=status.HTTP_200_OK)
def reset_draft_assignments(
    days_ahead: int = Query(ge=0),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    cutoff = date.today() + timedelta(days=days_ahead)
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "algorithm_draft",
            DutyAssignment.start_date >= cutoff,
        )
    ).scalars().all()

    # Drafts are invisible to soldiers — no notification needed, just reject and audit.
    for a in assignments:
        a.status = "algorithm_rejected"
        write_audit(
            session,
            actor_id=user.id,
            action="algorithm.proposal.bulk_reject",
            entity_type="duty_assignment",
            entity_id=a.id,
            before={"status": "algorithm_draft"},
            after={"status": "algorithm_rejected"},
            context={"days_ahead": days_ahead},
        )

    session.commit()
    return {"rejected": len(assignments)}


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
    _maybe_publish_job(session, job_id)
    session.commit()
    return {"status": "published"}


class BulkAcceptRequest(BaseModel):
    assignment_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/jobs/{job_id}/proposals/bulk-accept", status_code=status.HTTP_200_OK)
def bulk_accept_proposals(
    job_id: uuid.UUID,
    body: BulkAcceptRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    # Bulk UPDATE — one statement regardless of count
    result = session.execute(
        update(DutyAssignment)
        .where(
            DutyAssignment.id.in_(body.assignment_ids),
            DutyAssignment.status == "algorithm_draft",
        )
        .values(status="published")
        .returning(DutyAssignment.id)
    )
    accepted_ids = [row[0] for row in result]

    if accepted_ids:
        # Bulk INSERT into audit_log — one statement regardless of count
        session.execute(
            insert(AuditLog).values([
                {
                    "actor_id": user.id,
                    "action": "algorithm.proposal.accept",
                    "entity_type": "duty_assignment",
                    "entity_id": aid,
                    "before": {"status": "algorithm_draft"},
                    "after": {"status": "published"},
                    "context": {"job_id": str(job_id)},
                }
                for aid in accepted_ids
            ])
        )

    _maybe_publish_job(session, job_id)
    session.commit()
    return {"accepted": len(accepted_ids)}


@router.post("/jobs/{job_id}/proposals/bulk-reject", status_code=status.HTTP_200_OK)
def bulk_reject_proposals(
    job_id: uuid.UUID,
    body: BulkAcceptRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    result = session.execute(
        update(DutyAssignment)
        .where(
            DutyAssignment.id.in_(body.assignment_ids),
            DutyAssignment.status == "algorithm_draft",
        )
        .values(status="algorithm_rejected")
        .returning(DutyAssignment.id)
    )
    rejected_ids = [row[0] for row in result]

    if rejected_ids:
        session.execute(
            insert(AuditLog).values([
                {
                    "actor_id": user.id,
                    "action": "algorithm.proposal.bulk_reject",
                    "entity_type": "duty_assignment",
                    "entity_id": rid,
                    "before": {"status": "algorithm_draft"},
                    "after": {"status": "algorithm_rejected"},
                    "context": {"job_id": str(job_id)},
                }
                for rid in rejected_ids
            ])
        )

    _maybe_publish_job(session, job_id)
    session.commit()
    return {"rejected": len(rejected_ids)}


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
    _maybe_publish_job(session, job_id)
    session.commit()
    return {"status": "algorithm_rejected"}


@router.post("/proposals/{assignment_id}/accept", status_code=status.HTTP_200_OK)
def accept_proposal_direct(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    job_id = _job_id_for_assignment(session, assignment_id)
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
        context={"source": "direct"},
    )
    if job_id is not None:
        _maybe_publish_job(session, job_id)
    session.commit()
    return {"status": "published"}


@router.post("/proposals/{assignment_id}/reject", status_code=status.HTTP_200_OK)
def reject_proposal_direct(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    job_id = _job_id_for_assignment(session, assignment_id)
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
        context={"source": "direct"},
    )
    if job_id is not None:
        _maybe_publish_job(session, job_id)
    session.commit()
    return {"status": "algorithm_rejected"}
