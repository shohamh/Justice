from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, HierarchyNode, ScoreAdjustment, Soldier
from app.db.session import get_session
from app.services import adjustments as svc
from app.services.scoring import transparency_rows

router = APIRouter(prefix="/score-adjustments", tags=["score-adjustments"])


class AdjustmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    delta: Decimal
    reason: str
    duty_type_id: uuid.UUID | None
    created_at: datetime


class CreateAdjustmentRequest(BaseModel):
    soldier_id: uuid.UUID
    delta: Decimal = Field(ge=-9999, le=9999)
    reason: str = Field(min_length=1, max_length=1000)
    duty_type_id: uuid.UUID | None = None


def _out(a: ScoreAdjustment) -> AdjustmentOut:
    return AdjustmentOut(
        id=a.id,
        soldier_id=a.soldier_id,
        delta=a.delta,
        reason=a.reason,
        duty_type_id=a.duty_type_id,
        created_at=a.created_at,
    )


class PreviewOut(BaseModel):
    cumulative_score_before: str
    cumulative_score_after: str
    normalised_score_before: str
    normalised_score_after: str
    effort_score_before: str
    effort_score_after: str


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


@router.get("/preview", response_model=PreviewOut)
def preview_adjustment(
    soldier_id: uuid.UUID,
    delta: Decimal,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PreviewOut:
    from app.services.effort_score import compute_effort_breakdown, quarter_start
    from app.services.settings_loader import get_setting

    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))

    result = transparency_rows(session, viewer=user)
    rows = result["rows"]
    soldier_row = next((r for r in rows if r["soldier_id"] == soldier_id), None)
    if soldier_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="soldier_not_in_transparency")

    cum_before = Decimal(str(soldier_row["cumulative_score"]))
    spd_before = Decimal(str(soldier_row["score_per_day"]))
    normalised_before = Decimal(str(soldier_row["normalised_score"]))
    ad = int(soldier_row["active_days"])
    n = result["population_count"]

    cum_after = cum_before + delta
    spd_after = cum_after / Decimal(ad)

    # Recompute avg_spd with the updated soldier score_per_day
    old_avg_spd = spd_before / normalised_before if normalised_before != Decimal("0") else None
    if old_avg_spd is not None and n > 0:
        new_avg_spd = old_avg_spd + (spd_after - spd_before) / Decimal(n)
        normalised_after = spd_after / new_avg_spd if new_avg_spd != Decimal("0") else Decimal("0")
    else:
        normalised_after = Decimal("0")

    # Compute effort before/after using the breakdown service
    today = date.today()
    try:
        reset_raw = get_setting(session, "fairness.reset_date")
        reset_date = date.fromisoformat(str(reset_raw))
    except Exception:
        reset_date = quarter_start(date(today.year - 2, today.month, 1))

    latest_published_end = session.execute(
        select(func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        planning_start = latest_published_end + timedelta(days=1)
    else:
        planning_start = today

    bd_before = compute_effort_breakdown(
        session,
        soldier=s,
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=reset_date,
    )
    bd_after = compute_effort_breakdown(
        session,
        soldier=s,
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=reset_date,
        extra_adj_delta=delta,
        extra_adj_date=today,
    )

    return PreviewOut(
        cumulative_score_before=f"{cum_before:.3f}",
        cumulative_score_after=f"{cum_after:.3f}",
        normalised_score_before=f"{normalised_before:.4f}",
        normalised_score_after=f"{normalised_after:.4f}",
        effort_score_before=f"{bd_before.effort_score:.4f}",
        effort_score_after=f"{bd_after.effort_score:.4f}",
    )


@router.get("", response_model=list[AdjustmentOut])
def list_adjustments(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AdjustmentOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    return [_out(a) for a in svc.list_adjustments(session, soldier_id=soldier_id)]


@router.post("", response_model=AdjustmentOut, status_code=status.HTTP_201_CREATED)
def create_adjustment(
    body: CreateAdjustmentRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AdjustmentOut:
    s = _load_soldier(session, body.soldier_id)
    authorize(session, user, Action.SCORE_ADJUST, target_node=_node_of(session, s))
    try:
        adj = svc.create_adjustment(
            session,
            soldier_id=body.soldier_id,
            delta=body.delta,
            reason=body.reason,
            duty_type_id=body.duty_type_id,
            actor_id=user.id,
        )
    except svc.AdjustmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(adj)
    return _out(adj)
