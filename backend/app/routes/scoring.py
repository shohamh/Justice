from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import scoring as svc
from app.services.settings_loader import SettingNotFound, get_setting

router = APIRouter(prefix="/scoring", tags=["scoring"])


class ExemptionSummaryItem(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None


class TransparencyRow(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    node_id: uuid.UUID | None
    node_name: str | None
    enrolled_at: date
    active_days: int
    shift_count: int
    rank: str | None
    is_officer: bool | None
    service_type: str | None
    cumulative_score: Decimal
    score_per_day: Decimal
    normalised_score: Decimal
    is_globally_exempted: bool = False
    effort_score: float = 0.0
    c_over_d: float = 0.0
    effort_offset_raw: int = 0
    exemptions_display: str = ""
    exemptions_visible: bool = False
    exemptions: list[ExemptionSummaryItem] = []
    has_global_exemption: bool | None = None
    has_partial_exemption: bool | None = None
    has_temporary_exemption: bool | None = None


class TransparencyOut(BaseModel):
    rows: list[TransparencyRow]
    can_see_exemption_aggregates: bool


class PerTypeRow(BaseModel):
    duty_type_id: uuid.UUID
    duty_type_name: str | None
    days: int
    days_past: int
    days_future: int
    score: Decimal


class AdjustmentRow(BaseModel):
    id: uuid.UUID
    delta: Decimal
    reason: str
    created_at: datetime


class BreakdownOut(BaseModel):
    per_type: list[PerTypeRow]
    adjustments: list[AdjustmentRow]


class EffortQuarterRow(BaseModel):
    quarter_start: date
    quarter_end: date
    quarter_label: str
    soldier_score: Decimal
    unit_score: Decimal
    active_frac: Decimal
    share: Decimal
    weighted_share: Decimal
    is_partial: bool = False
    adjustment_delta: Decimal = Decimal("0")


class EffortBreakdownOut(BaseModel):
    quarters: list[EffortQuarterRow]
    effort_score: Decimal
    A_i: Decimal   # Σ(s_q × active_frac_q) — personal weighted score
    W_i: Decimal   # Σ(U_q × active_frac_q) — unit weighted score


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _transparency_allowed(session: Session, user: Soldier) -> bool:
    try:
        levels = get_setting(session, "transparency.visible_commander_levels")
    except SettingNotFound:
        levels = None
    if not levels:
        return True  # no restriction configured — everyone can view (default, matches today)
    if user.role in ("admin", "duty_manager"):
        return True
    return session.execute(
        select(HierarchyNode.id).where(
            HierarchyNode.commander_id == user.id,
            HierarchyNode.level.in_(levels),
        ).limit(1)
    ).first() is not None


@router.get("/transparency", response_model=TransparencyOut)
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransparencyOut:
    if not _transparency_allowed(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="transparency_hidden")
    result = svc.transparency_rows(session, viewer=user)
    return TransparencyOut(
        rows=[TransparencyRow(**row) for row in result["rows"]],
        can_see_exemption_aggregates=result["can_see_exemption_aggregates"],
    )


@router.get("/fairness-components")
def fairness_components(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    """Effort spread (פיזור) split per connected component of soldiers who share
    duty-type eligibility, plus the count of soldiers exempt from every duty."""
    return svc.fairness_components(session)


@router.get("/eligibility-groups")
def eligibility_groups(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[dict]:
    """Lightweight view of fairness_components() for scoping auto-assign selection —
    same connected components, without the per-soldier detail."""
    full = svc.fairness_components(session)
    return [
        {
            "duty_type_ids": c["duty_type_ids"],
            "duty_type_names": c["duty_type_names"],
            "soldier_count": c["soldier_count"],
        }
        for c in full["components"]
    ]


@router.get("/soldiers/{soldier_id}/effort-breakdown", response_model=EffortBreakdownOut)
def effort_breakdown(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> EffortBreakdownOut:
    from app.services.effort_score import compute_effort_breakdown, quarter_start
    from app.services.settings_loader import SettingNotFound, get_setting

    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))

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

    bd = compute_effort_breakdown(
        session,
        soldier=s,
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=reset_date,
    )
    return EffortBreakdownOut(
        quarters=[
            EffortQuarterRow(
                quarter_start=q.quarter_start,
                quarter_end=q.quarter_end,
                quarter_label=q.quarter_label,
                soldier_score=q.soldier_score,
                unit_score=q.unit_score,
                active_frac=q.active_frac,
                share=q.share,
                weighted_share=q.weighted_share,
                is_partial=q.is_partial,
                adjustment_delta=q.adjustment_delta,
            )
            for q in bd.quarters
        ],
        effort_score=bd.effort_score,
        A_i=bd.A_i,
        W_i=bd.W_i,
    )


@router.get("/soldiers/{soldier_id}", response_model=BreakdownOut)
def breakdown(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BreakdownOut:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    data = svc.soldier_score_breakdown(session, soldier_id=soldier_id)
    return BreakdownOut(
        per_type=[PerTypeRow(**pt) for pt in data["per_type"]],
        adjustments=[
            AdjustmentRow(id=a.id, delta=a.delta, reason=a.reason, created_at=a.created_at)
            for a in data["adjustments"]
        ],
    )
