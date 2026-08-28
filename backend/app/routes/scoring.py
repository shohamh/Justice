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
from app.services.authority import can_view_soldier_scope, has_any_visibility

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
    burden_share: float = 0.0
    c_over_d: float = 0.0
    burden_share_offset_raw: int = 0
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


class BurdenShareContributionOut(BaseModel):
    kind: str                 # "duty" | "adjustment"
    label: str
    detail: str = ""
    score: Decimal
    start_date: date | None = None   # inclusive, duty spans only
    end_date: date | None = None     # inclusive, duty spans only
    days: int = 0
    multiplier: Decimal = Decimal("1")


class BurdenShareQuarterRow(BaseModel):
    quarter_start: date
    quarter_end: date
    quarter_label: str
    soldier_score: Decimal
    unit_score: Decimal
    active_frac: Decimal
    share: Decimal
    weighted_share: Decimal
    is_partial: bool
    adjustment_delta: Decimal = Decimal("0")
    contributions: list[BurdenShareContributionOut] = []


class BurdenShareBreakdownOut(BaseModel):
    quarters: list[BurdenShareQuarterRow]
    burden_share: Decimal
    A_i: Decimal   # Σ(s_q × active_frac_q) — personal weighted score
    W_i: Decimal   # Σ(U_q × active_frac_q) — unit weighted score


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


@router.get("/transparency", response_model=TransparencyOut)
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransparencyOut:
    if not has_any_visibility(session, user):
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
    """Burden-share spread (פיזור) split per connected component of soldiers who share
    duty-type eligibility, plus the count of soldiers exempt from every duty."""
    if not has_any_visibility(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="transparency_hidden")
    return svc.fairness_components(session, viewer=user)


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


@router.get("/soldiers/{soldier_id}/burden-share-breakdown", response_model=BurdenShareBreakdownOut)
def burden_share_breakdown(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BurdenShareBreakdownOut:
    from app.services.effort_score import compute_burden_share_breakdown
    from app.services.scoring import _burden_share_reset_date

    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        if not can_view_soldier_scope(session, user, _node_of(session, s)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    reset_date = _burden_share_reset_date(session)

    today = date.today()

    latest_published_end = session.execute(
        select(func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        planning_start = latest_published_end + timedelta(days=1)
    else:
        planning_start = today

    bd = compute_burden_share_breakdown(
        session,
        soldier=s,
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=reset_date,
    )
    return BurdenShareBreakdownOut(
        quarters=[
            BurdenShareQuarterRow(
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
                contributions=[
                    BurdenShareContributionOut(
                        kind=c.kind,
                        label=c.label,
                        detail=c.detail,
                        score=c.score,
                        start_date=c.start_date,
                        end_date=c.end_date,
                        days=c.days,
                        multiplier=c.multiplier,
                    )
                    for c in q.contributions
                ],
            )
            for q in bd.quarters
        ],
        burden_share=bd.burden_share,
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
