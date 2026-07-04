from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import assignments as svc
from app.services import scoring as scoring_svc

router = APIRouter(prefix="/assignments", tags=["assignments"])

_CONFLICT = {"overlap", "exempted", "insufficient_rest"}


class AssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    notes: str | None


class CreateAssignmentRequest(BaseModel):
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    notes: str | None = Field(default=None, max_length=1000)
    duty_shift_id: uuid.UUID | None = None
    is_reserve: bool = False


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class OverrideRequest(BaseModel):
    effective_soldier_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=50)


class EffectiveDutyOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    start_at: datetime
    end_at: datetime
    shift_id: uuid.UUID | None = None
    is_reserve: bool = False


def _out(a: DutyAssignment) -> AssignmentOut:
    return AssignmentOut(
        id=a.id,
        soldier_id=a.soldier_id,
        duty_type_id=a.duty_type_id,
        duty_location_id=a.duty_location_id,
        start_date=a.start_date,
        end_date=a.end_date,
        status=a.status,
        notes=a.notes,
    )


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _load_assignment(session: Session, assignment_id: uuid.UUID) -> DutyAssignment:
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return a


def _err(exc: svc.AssignmentError) -> HTTPException:
    detail = str(exc)
    code = status.HTTP_409_CONFLICT if detail in _CONFLICT else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


@router.get("", response_model=list[AssignmentOut])
def list_assignments(
    soldier_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AssignmentOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    rows = svc.list_assignments(
        session, soldier_id=soldier_id, date_from=date_from, date_to=date_to
    )
    return [_out(a) for a in rows]


@router.get("/effective", response_model=list[EffectiveDutyOut])
def list_effective_duties(
    soldier_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EffectiveDutyOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    spans = scoring_svc.effective_duty_spans(
        session, soldier_ids={soldier_id}, date_from=date_from, date_to=date_to
    )
    return [EffectiveDutyOut(**sp) for sp in spans]


@router.post("", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def create_assignment(
    body: CreateAssignmentRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AssignmentOut:
    s = _load_soldier(session, body.soldier_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of(session, s))
    try:
        a = svc.create_assignment(
            session,
            soldier_id=body.soldier_id,
            duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id,
            start_date=body.start_date,
            end_date=body.end_date,
            notes=body.notes,
            duty_shift_id=body.duty_shift_id,
            is_reserve=body.is_reserve,
            actor_id=user.id,
        )
    except svc.AssignmentError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(a)
    return _out(a)


@router.post("/{assignment_id}/cancel", response_model=AssignmentOut)
def cancel_assignment(
    assignment_id: uuid.UUID,
    body: CancelRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AssignmentOut:
    a = _load_assignment(session, assignment_id)
    authorize(
        session,
        user,
        Action.ASSIGNMENT_MANAGE,
        target_node=_node_of(session, _load_soldier(session, a.soldier_id)),
    )
    try:
        svc.cancel_assignment(session, assignment=a, reason=body.reason, actor_id=user.id)
    except svc.AssignmentError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(a)
    return _out(a)


@router.put("/{assignment_id}/overrides/{day}", status_code=status.HTTP_200_OK)
def set_override(
    assignment_id: uuid.UUID,
    day: date,
    body: OverrideRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    a = _load_assignment(session, assignment_id)
    authorize(
        session,
        user,
        Action.ASSIGNMENT_MANAGE,
        target_node=_node_of(session, _load_soldier(session, a.soldier_id)),
    )
    try:
        svc.set_day_override(
            session,
            assignment=a,
            date=day,
            effective_soldier_id=body.effective_soldier_id,
            reason=body.reason,
            actor_id=user.id,
        )
    except svc.AssignmentError as exc:
        raise _err(exc) from exc
    session.commit()
    return {"status": "ok"}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def clear_all_assignments(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    """Cancel all non-cancelled assignments (admin / duty-manager operation)."""
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    session.execute(
        sa_update(DutyAssignment)
        .where(DutyAssignment.status != "cancelled")
        .values(status="cancelled")
    )
    session.commit()


@router.delete("/{assignment_id}/overrides/{day}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def clear_override(
    assignment_id: uuid.UUID,
    day: date,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    a = _load_assignment(session, assignment_id)
    authorize(
        session,
        user,
        Action.ASSIGNMENT_MANAGE,
        target_node=_node_of(session, _load_soldier(session, a.soldier_id)),
    )
    svc.clear_day_override(session, assignment=a, date=day, actor_id=user.id)
    session.commit()
