from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, DutyNoShow, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import no_show as svc

router = APIRouter(prefix="/no-shows", tags=["no-shows"])


class MarkNoShowBody(BaseModel):
    duty_assignment_id: uuid.UUID
    note: str = Field(min_length=1, max_length=1000)
    penalty_delta: Decimal = Field(default=Decimal("-1"), ge=-9999, le=0)


class NoShowOut(BaseModel):
    id: uuid.UUID
    duty_assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    marked_by: uuid.UUID | None
    note: str
    score_adjustment_id: uuid.UUID | None
    created_at: datetime


def _out(r: DutyNoShow) -> NoShowOut:
    return NoShowOut(
        id=r.id, duty_assignment_id=r.duty_assignment_id, soldier_id=r.soldier_id,
        marked_by=r.marked_by, note=r.note, score_adjustment_id=r.score_adjustment_id,
        created_at=r.created_at,
    )


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


@router.post("", response_model=NoShowOut, status_code=status.HTTP_201_CREATED)
def mark_no_show(
    body: MarkNoShowBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NoShowOut:
    assignment = session.get(DutyAssignment, body.duty_assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    soldier = _load_soldier(session, assignment.soldier_id)
    authorize(session, user, Action.SCORE_ADJUST, target_node=_node_of(session, soldier))
    try:
        record = svc.mark_no_show(
            session,
            duty_assignment_id=body.duty_assignment_id,
            marked_by=user.id,
            note=body.note,
            penalty_delta=body.penalty_delta,
        )
    except svc.NoShowError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(record)
    return _out(record)


@router.get("/soldiers/{soldier_id}", response_model=list[NoShowOut])
def list_no_shows_for_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NoShowOut]:
    soldier = _load_soldier(session, soldier_id)
    if soldier.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, soldier))
    return [_out(r) for r in svc.list_no_shows(session, soldier_id=soldier_id)]
