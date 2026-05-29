from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, ScoreAdjustment, Soldier
from app.db.session import get_session
from app.services import adjustments as svc

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
    delta: Decimal
    reason: str = Field(min_length=1, max_length=1000)
    duty_type_id: uuid.UUID | None = None


def _out(a: ScoreAdjustment) -> AdjustmentOut:
    return AdjustmentOut(id=a.id, soldier_id=a.soldier_id, delta=a.delta, reason=a.reason,
                         duty_type_id=a.duty_type_id, created_at=a.created_at)


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


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
        adj = svc.create_adjustment(session, soldier_id=body.soldier_id, delta=body.delta,
                                    reason=body.reason, duty_type_id=body.duty_type_id, actor_id=user.id)
    except svc.AdjustmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(adj)
    return _out(adj)
