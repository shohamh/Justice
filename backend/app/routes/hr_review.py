from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.auth.deps import require_roles
from app.db.models import (
    AuditLog,
    HrHierarchySync,
    HrIdentityConflict,
    HrPersonSync,
    HrPersonSyncError,
    HrPreferredRecord,
    HrRankConflict,
    Soldier,
    SoldierHrProfile,
)
from app.db.session import get_session
from app.hr_sync_worker import SyncAlreadyRunningError, run_sync_now_in_own_session
from app.services.hr.conflict_actions import (
    ConflictActionError,
    acknowledge_conflict,
    candidate_choice_status,
    choose_candidate,
    clear_preference,
)
from app.services.hr.review import ReviewActionError, clear_field_override, dismiss_held_for_review
from app.settings import get_settings

router = APIRouter(prefix="/admin/hr-sync", tags=["hr-review"])


class HeldForReviewItemOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    review_reason: str | None
    last_synced_at: datetime | None
    raw_dto: dict[str, object] | None = None


class HeldForReviewPageOut(BaseModel):
    items: list[HeldForReviewItemOut]


@router.get("/held-for-review", response_model=HeldForReviewPageOut)
def list_held_for_review(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HeldForReviewPageOut:
    rows = session.execute(
        select(SoldierHrProfile).where(
            SoldierHrProfile.sync_status == "held_for_review",
            SoldierHrProfile.review_dismissed_at.is_(None),
        ).order_by(SoldierHrProfile.last_synced_at.desc())
    ).scalars().all()
    return HeldForReviewPageOut(items=[
        HeldForReviewItemOut(
            id=r.id, personal_number=r.personal_number,
            review_reason=r.review_reason, last_synced_at=r.last_synced_at,
            raw_dto=r.raw_dto,
        ) for r in rows
    ])


@router.post("/held-for-review/{profile_id}/dismiss", response_model=HeldForReviewItemOut)
def dismiss_held_for_review_route(
    profile_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HeldForReviewItemOut:
    try:
        profile = dismiss_held_for_review(session, profile_id=profile_id, actor_id=user.id)
    except ReviewActionError as exc:
        session.rollback()
        code = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if code == "profile_not_found" else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=status_code, detail=code) from exc
    session.commit()
    return HeldForReviewItemOut(
        id=profile.id, personal_number=profile.personal_number,
        review_reason=profile.review_reason, last_synced_at=profile.last_synced_at,
    )


class DivergenceItemOut(BaseModel):
    id: uuid.UUID
    soldier_hr_profile_id: uuid.UUID
    soldier_full_name: str | None
    soldier_personal_number: str | None
    field_name: str
    hr_value: object
    local_value: object
    created_at: datetime


class DivergencePageOut(BaseModel):
    items: list[DivergenceItemOut]


@router.get("/divergences", response_model=DivergencePageOut)
def list_divergences(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> DivergencePageOut:
    # A field that stays overridden across many sync runs would otherwise
    # keep piling up one "hr_sync.field_skipped_overridden" audit row per
    # run, so this selects only the LATEST row per (profile, field) pair
    # (a Postgres DISTINCT ON, ordered to match) and, since clear_field_override
    # removes the field from overridden_fields without deleting old audit
    # rows, also drops any pair whose field is no longer actually overridden.
    field_name_expr = AuditLog.context["field_name"].astext
    latest_subq = (
        select(AuditLog)
        .join(SoldierHrProfile, SoldierHrProfile.id == AuditLog.entity_id)
        .where(
            AuditLog.action == "hr_sync.field_skipped_overridden",
            func.jsonb_exists(SoldierHrProfile.overridden_fields, field_name_expr),
        )
        .order_by(AuditLog.entity_id, field_name_expr, AuditLog.created_at.desc(), AuditLog.id.desc())
        .distinct(AuditLog.entity_id, field_name_expr)
        .subquery()
    )
    latest = aliased(AuditLog, latest_subq)
    rows = session.execute(
        select(latest)
        .order_by(latest.created_at.desc(), latest.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    profile_ids = {r.entity_id for r in rows if r.entity_id is not None}
    soldier_by_profile_id: dict[uuid.UUID, Soldier] = {}
    if profile_ids:
        for profile_id, soldier in session.execute(
            select(SoldierHrProfile.id, Soldier)
            .join(Soldier, Soldier.id == SoldierHrProfile.soldier_id)
            .where(SoldierHrProfile.id.in_(profile_ids))
        ).all():
            soldier_by_profile_id[profile_id] = soldier

    return DivergencePageOut(items=[
        DivergenceItemOut(
            id=r.id, soldier_hr_profile_id=r.entity_id,
            soldier_full_name=soldier_by_profile_id[r.entity_id].full_name if r.entity_id in soldier_by_profile_id else None,
            soldier_personal_number=soldier_by_profile_id[r.entity_id].personal_number if r.entity_id in soldier_by_profile_id else None,
            field_name=(r.context or {}).get("field_name", ""),
            hr_value=(r.context or {}).get("hr_value"),
            local_value=(r.context or {}).get("local_value"),
            created_at=r.created_at,
        ) for r in rows
    ])


class ClearOverrideIn(BaseModel):
    field_name: str


@router.post("/divergences/{profile_id}/clear-override", response_model=HeldForReviewItemOut)
def clear_override_route(
    profile_id: uuid.UUID,
    body: ClearOverrideIn,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HeldForReviewItemOut:
    try:
        profile = clear_field_override(
            session, profile_id=profile_id, field_name=body.field_name, actor_id=user.id,
        )
    except ReviewActionError as exc:
        session.rollback()
        code = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if code == "profile_not_found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=code) from exc
    session.commit()
    return HeldForReviewItemOut(
        id=profile.id, personal_number=profile.personal_number,
        review_reason=profile.review_reason, last_synced_at=profile.last_synced_at,
    )


class VanishedItemOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    last_synced_at: datetime | None


class VanishedPageOut(BaseModel):
    items: list[VanishedItemOut]


@router.get("/vanished", response_model=VanishedPageOut)
def list_vanished(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> VanishedPageOut:
    rows = session.execute(
        select(SoldierHrProfile)
        .where(SoldierHrProfile.sync_status == "vanished")
        .order_by(SoldierHrProfile.last_synced_at.desc())
    ).scalars().all()
    return VanishedPageOut(items=[
        VanishedItemOut(id=r.id, personal_number=r.personal_number, last_synced_at=r.last_synced_at)
        for r in rows
    ])


class RankConflictItemOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_full_name: str | None
    soldier_personal_number: str | None
    old_rank: str | None
    new_rank: str | None
    triggered_by_worker_decision: bool
    non_sequential_jump: bool
    created_at: datetime


class RankConflictPageOut(BaseModel):
    items: list[RankConflictItemOut]


@router.get("/rank-conflicts", response_model=RankConflictPageOut)
def list_rank_conflicts(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> RankConflictPageOut:
    rows = session.execute(
        select(HrRankConflict, Soldier)
        .outerjoin(Soldier, Soldier.id == HrRankConflict.soldier_id)
        .order_by(HrRankConflict.created_at.desc())
    ).all()
    return RankConflictPageOut(items=[
        RankConflictItemOut(
            id=r.id, soldier_id=r.soldier_id,
            soldier_full_name=soldier.full_name if soldier else None,
            soldier_personal_number=soldier.personal_number if soldier else None,
            old_rank=r.old_rank, new_rank=r.new_rank,
            triggered_by_worker_decision=r.triggered_by_worker_decision,
            non_sequential_jump=r.non_sequential_jump, created_at=r.created_at,
        ) for r, soldier in rows
    ])


class SyncErrorOut(BaseModel):
    personal_number: str
    error_message: str


class PersonSyncRunOut(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    total_fetched: int
    created_count: int
    updated_count: int
    held_count: int
    vanished_count: int
    error_count: int
    conflict_count: int
    error_message: str | None
    errors: list[SyncErrorOut]


class HierarchySyncRunOut(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    created_count: int
    matched_count: int
    held_count: int
    error_message: str | None


class SyncRunsOut(BaseModel):
    person_syncs: list[PersonSyncRunOut]
    hierarchy_syncs: list[HierarchySyncRunOut]


@router.get("/runs", response_model=SyncRunsOut)
def list_sync_runs(
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> SyncRunsOut:
    person_runs = session.execute(
        select(HrPersonSync).order_by(HrPersonSync.started_at.desc()).limit(limit)
    ).scalars().all()
    hierarchy_runs = session.execute(
        select(HrHierarchySync).order_by(HrHierarchySync.started_at.desc()).limit(limit)
    ).scalars().all()

    person_out = []
    for run in person_runs:
        errors = session.execute(
            select(HrPersonSyncError).where(HrPersonSyncError.hr_person_sync_id == run.id)
        ).scalars().all()
        person_out.append(PersonSyncRunOut(
            id=run.id, status=run.status, started_at=run.started_at, completed_at=run.completed_at,
            total_fetched=run.total_fetched, created_count=run.created_count,
            updated_count=run.updated_count, held_count=run.held_count,
            vanished_count=run.vanished_count, error_count=run.error_count,
            conflict_count=run.conflict_count, error_message=run.error_message,
            errors=[SyncErrorOut(personal_number=e.personal_number, error_message=e.error_message) for e in errors],
        ))

    hierarchy_out = [
        HierarchySyncRunOut(
            id=run.id, status=run.status, started_at=run.started_at, completed_at=run.completed_at,
            created_count=run.created_count, matched_count=run.matched_count,
            held_count=run.held_count, error_message=run.error_message,
        ) for run in hierarchy_runs
    ]

    return SyncRunsOut(person_syncs=person_out, hierarchy_syncs=hierarchy_out)


class RunNowOut(BaseModel):
    hierarchy_sync_id: uuid.UUID | None
    person_sync_id: uuid.UUID | None


@router.post("/run-now", response_model=RunNowOut)
async def run_sync_now(
    user: Soldier = Depends(require_roles("admin")),
) -> RunNowOut:
    settings = get_settings()
    if not settings.hr_sync_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="hr_sync_not_configured")
    try:
        hierarchy_sync_id, person_sync_id = await asyncio.to_thread(run_sync_now_in_own_session)
    except SyncAlreadyRunningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="hr_sync_already_running") from exc
    return RunNowOut(hierarchy_sync_id=hierarchy_sync_id, person_sync_id=person_sync_id)


# ── Identity conflicts (duplicate HR records, email / AD username collisions) ──


class HrConflictCandidateOut(BaseModel):
    index: int
    key_type: str | None
    key_value: str | None
    payload: dict[str, object]
    is_applied: bool
    choosable: bool
    invalid_reason: str | None


class CollidingSoldierOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str | None
    personal_number: str | None


class PreferredRecordOut(BaseModel):
    personal_number: str
    key_type: str
    key_value: str
    chosen_by: uuid.UUID | None
    chosen_by_name: str | None
    chosen_at: datetime


class HrIdentityConflictOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    kind: str
    reason: str
    status: str
    applied_index: int | None
    chosen_index: int | None
    candidates: list[HrConflictCandidateOut]
    colliding_soldiers: list[CollidingSoldierOut]
    preferred_record: PreferredRecordOut | None
    hr_person_sync_id: uuid.UUID | None
    created_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None


class HrIdentityConflictPageOut(BaseModel):
    items: list[HrIdentityConflictOut]


class ChooseCandidateIn(BaseModel):
    candidate_index: int


class PreferredRecordPageOut(BaseModel):
    items: list[PreferredRecordOut]


def _preferred_out(session: Session, preference: HrPreferredRecord) -> PreferredRecordOut:
    chooser = session.get(Soldier, preference.chosen_by) if preference.chosen_by else None
    return PreferredRecordOut(
        personal_number=preference.personal_number, key_type=preference.key_type,
        key_value=preference.key_value, chosen_by=preference.chosen_by,
        chosen_by_name=chooser.full_name if chooser else None, chosen_at=preference.chosen_at,
    )


def _conflict_out(session: Session, conflict: HrIdentityConflict) -> HrIdentityConflictOut:
    if conflict.status in ("open", "acknowledged"):
        choice = candidate_choice_status(session, conflict)
    else:
        choice = ["conflict_not_active"] * len(conflict.candidates)
    colliding = []
    for soldier_id in conflict.colliding_soldier_ids:
        soldier = session.get(Soldier, uuid.UUID(soldier_id))
        if soldier is not None:
            colliding.append(CollidingSoldierOut(
                soldier_id=soldier.id, full_name=soldier.full_name, personal_number=soldier.personal_number,
            ))
    preference = session.execute(
        select(HrPreferredRecord).where(HrPreferredRecord.personal_number == conflict.personal_number)
    ).scalar_one_or_none()
    return HrIdentityConflictOut(
        id=conflict.id, personal_number=conflict.personal_number, kind=conflict.kind,
        reason=conflict.reason, status=conflict.status, applied_index=conflict.applied_index,
        chosen_index=conflict.chosen_index,
        candidates=[
            HrConflictCandidateOut(
                index=c["index"], key_type=c.get("key_type"), key_value=c.get("key_value"),
                payload=c["payload"], is_applied=c["index"] == conflict.applied_index,
                choosable=choice[i] is None, invalid_reason=choice[i],
            ) for i, c in enumerate(conflict.candidates)
        ],
        colliding_soldiers=colliding,
        preferred_record=_preferred_out(session, preference) if preference else None,
        hr_person_sync_id=conflict.hr_person_sync_id, created_at=conflict.created_at,
        last_seen_at=conflict.last_seen_at, acknowledged_at=conflict.acknowledged_at,
        resolved_at=conflict.resolved_at,
    )


def _action_error(session: Session, exc: ConflictActionError) -> HTTPException:
    session.rollback()
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/identity-conflicts", response_model=HrIdentityConflictPageOut)
def list_identity_conflicts(
    status_filter: Literal["open", "acknowledged", "resolved", "all"] = Query("open", alias="status"),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HrIdentityConflictPageOut:
    query = select(HrIdentityConflict).order_by(
        HrIdentityConflict.last_seen_at.desc(), HrIdentityConflict.id
    )
    if status_filter != "all":
        query = query.where(HrIdentityConflict.status == status_filter)
    rows = session.execute(query).scalars().all()
    return HrIdentityConflictPageOut(items=[_conflict_out(session, row) for row in rows])


@router.post("/identity-conflicts/{conflict_id}/acknowledge", response_model=HrIdentityConflictOut)
def acknowledge_identity_conflict(
    conflict_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HrIdentityConflictOut:
    try:
        conflict = acknowledge_conflict(session, conflict_id, actor_id=user.id)
    except ConflictActionError as exc:
        raise _action_error(session, exc) from exc
    session.commit()
    return _conflict_out(session, conflict)


@router.post("/identity-conflicts/{conflict_id}/choose", response_model=HrIdentityConflictOut)
def choose_identity_conflict_record(
    conflict_id: uuid.UUID,
    body: ChooseCandidateIn,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> HrIdentityConflictOut:
    try:
        conflict = choose_candidate(session, conflict_id, body.candidate_index, actor_id=user.id)
        session.commit()
    except ConflictActionError as exc:
        raise _action_error(session, exc) from exc
    return _conflict_out(session, conflict)


@router.get("/preferred-records", response_model=PreferredRecordPageOut)
def list_preferred_records(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> PreferredRecordPageOut:
    rows = session.execute(
        select(HrPreferredRecord).order_by(HrPreferredRecord.personal_number)
    ).scalars().all()
    return PreferredRecordPageOut(items=[_preferred_out(session, row) for row in rows])


@router.delete("/preferred-records/{personal_number}", status_code=status.HTTP_204_NO_CONTENT)
def clear_preferred_record(
    personal_number: str,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> None:
    try:
        clear_preference(session, personal_number, actor_id=user.id)
    except ConflictActionError as exc:
        raise _action_error(session, exc) from exc
    session.commit()
