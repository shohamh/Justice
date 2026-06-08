from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, can, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import gimelim as svc
from app.services.gimelim import GimelimError
from app.services.settings_loader import SettingNotFound, get_setting

router = APIRouter(tags=["gimelim"])


def _require_gimelim_enabled(session: Session) -> None:
    try:
        enabled = get_setting(session, "gimalim.enabled")
        if not bool(enabled):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="gimelim_disabled")
    except SettingNotFound:
        pass  # enabled by default


def _require_gimelim_permission(
    session: Session,
    user: Soldier,
    primary_soldier_id: uuid.UUID,
) -> None:
    """Admin or commander/DM in scope of the primary soldier."""
    if user.role == "admin":
        return
    soldier = session.get(Soldier, primary_soldier_id)
    if soldier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="soldier_not_found")
    target_node: HierarchyNode | None = None
    if soldier.hierarchy_node_id:
        target_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    roots = scope_root_ids(session, user)
    if not can(user, Action.ASSIGNMENT_MANAGE, target_node=target_node, roots=roots):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


# ── Pydantic models ─────────────────────────────────────────────────────────

class GimelimPreviewRequest(BaseModel):
    primary_assignment_id: uuid.UUID
    rest_days: int = Field(default=7, ge=0, le=365)
    reason: str | None = Field(default=None, max_length=1000)


class SoldierRefOut(BaseModel):
    id: uuid.UUID
    name: str
    rank: str | None


class ShiftRefOut(BaseModel):
    shift_id: uuid.UUID
    duty_type_name: str
    duty_location_name: str
    start_date: date
    end_date: date


class FutureAssignmentPreviewOut(BaseModel):
    shift: ShiftRefOut
    soldier_demoted: SoldierRefOut
    demoted_assignment_id: uuid.UUID
    c_existing_reserve_assignment_id: uuid.UUID | None
    c_existing_reserve_soldier: SoldierRefOut | None


class GimelimPreviewOut(BaseModel):
    preview_token: str
    preview_token_expires_at: datetime
    current_shift: ShiftRefOut
    soldier_a: SoldierRefOut
    primary_assignment_id: uuid.UUID
    reserve_assignment_id: uuid.UUID
    reserve_soldier: SoldierRefOut
    future_assignment: FutureAssignmentPreviewOut | None
    warnings: list[str]


class GimelimCommitRequest(BaseModel):
    preview_token: str


class GimelimCommitOut(BaseModel):
    dismissal_id: uuid.UUID
    call_up_assignment_id: uuid.UUID
    future_primary_assignment_id: uuid.UUID | None
    future_demoted_assignment_id: uuid.UUID | None
    notifications_queued: int


def _preview_to_out(p: svc.GimelimPreview) -> GimelimPreviewOut:
    def s(ref: svc.SoldierRef | None) -> SoldierRefOut | None:
        if ref is None:
            return None
        return SoldierRefOut(id=ref.id, name=ref.name, rank=ref.rank)

    def sh(ref: svc.ShiftRef) -> ShiftRefOut:
        return ShiftRefOut(
            shift_id=ref.shift_id,
            duty_type_name=ref.duty_type_name,
            duty_location_name=ref.duty_location_name,
            start_date=ref.start_date,
            end_date=ref.end_date,
        )

    fa: FutureAssignmentPreviewOut | None = None
    if p.future_assignment:
        f = p.future_assignment
        fa = FutureAssignmentPreviewOut(
            shift=sh(f.shift),
            soldier_demoted=SoldierRefOut(
                id=f.soldier_demoted.id,
                name=f.soldier_demoted.name,
                rank=f.soldier_demoted.rank,
            ),
            demoted_assignment_id=f.demoted_assignment_id,
            c_existing_reserve_assignment_id=f.c_existing_reserve_assignment_id,
            c_existing_reserve_soldier=s(f.c_existing_reserve_soldier),
        )

    return GimelimPreviewOut(
        preview_token=p.preview_token,
        preview_token_expires_at=p.preview_token_expires_at,
        current_shift=sh(p.current_shift),
        soldier_a=SoldierRefOut(id=p.soldier_a.id, name=p.soldier_a.name, rank=p.soldier_a.rank),
        primary_assignment_id=p.primary_assignment_id,
        reserve_assignment_id=p.reserve_assignment_id,
        reserve_soldier=SoldierRefOut(
            id=p.reserve_soldier.id, name=p.reserve_soldier.name, rank=p.reserve_soldier.rank
        ),
        future_assignment=fa,
        warnings=p.warnings,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/shifts/{shift_id}/gimelim/preview", response_model=GimelimPreviewOut)
def preview_gimelim_route(
    shift_id: uuid.UUID,
    body: GimelimPreviewRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> GimelimPreviewOut:
    _require_gimelim_enabled(session)

    # Load the primary assignment to get soldier_id for scope check
    primary_a = session.get(DutyAssignment, body.primary_assignment_id)
    if primary_a is None:
        raise HTTPException(status_code=404, detail="primary_not_found")
    _require_gimelim_permission(session, user, primary_a.soldier_id)

    try:
        preview = svc.preview_gimelim(
            session,
            shift_id=shift_id,
            primary_assignment_id=body.primary_assignment_id,
            rest_days=body.rest_days,
            reason=body.reason,
            actor_id=user.id,
        )
    except GimelimError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _preview_to_out(preview)


@router.post("/shifts/{shift_id}/gimelim/commit", response_model=GimelimCommitOut)
def commit_gimelim_route(
    shift_id: uuid.UUID,
    body: GimelimCommitRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> GimelimCommitOut:
    _require_gimelim_enabled(session)

    try:
        result = svc.commit_gimelim(
            session,
            shift_id=shift_id,
            preview_token=body.preview_token,
            actor_id=user.id,
        )
    except GimelimError as exc:
        code = status.HTTP_409_CONFLICT if "stale" in str(exc) or "expired" in str(exc) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    session.commit()
    return GimelimCommitOut(
        dismissal_id=result.dismissal_id,
        call_up_assignment_id=result.call_up_assignment_id,
        future_primary_assignment_id=result.future_primary_assignment_id,
        future_demoted_assignment_id=result.future_demoted_assignment_id,
        notifications_queued=result.notifications_queued,
    )
