from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import scoring as svc

router = APIRouter(prefix="/scoring", tags=["scoring"])


class TransparencyRow(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    node_id: uuid.UUID | None
    node_name: str | None
    enrolled_at: date
    active_days: int
    cumulative_score: Decimal
    score_per_day: Decimal
    normalised_score: Decimal


class PerTypeRow(BaseModel):
    duty_type_id: uuid.UUID
    duty_type_name: str | None
    days: int
    score: Decimal


class AdjustmentRow(BaseModel):
    id: uuid.UUID
    delta: Decimal
    reason: str
    created_at: datetime


class BreakdownOut(BaseModel):
    per_type: list[PerTypeRow]
    adjustments: list[AdjustmentRow]


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


@router.get("/transparency", response_model=list[TransparencyRow])
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TransparencyRow]:
    return [TransparencyRow(**row) for row in svc.transparency_rows(session)]


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
