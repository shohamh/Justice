from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, DutyShift, Soldier
from app.db.session import get_session
from app.services import shifts as svc

router = APIRouter(prefix="/shifts", tags=["shifts"])


class ShiftOut(BaseModel):
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int
    notes: str | None
    assigned_count: int
    reserve_assigned_count: int
    fill_status: str
    reserve_count_override: int | None = None
    calculated_reserve_count: int | None = None


class CreateShiftRequest(BaseModel):
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int = Field(default=1, ge=1)
    notes: str | None = Field(default=None, max_length=1000)
    reserve_count_override: int | None = Field(default=None, ge=0)


class UpdateShiftRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    required_count: int | None = Field(default=None, ge=1)
    notes: str | None = None
    reserve_count_override: int | None = Field(default=None, ge=0)
    eligible_node_ids: list[uuid.UUID] | None = None


def _out(s: svc.ShiftWithFill, session: Session | None = None) -> ShiftOut:
    calculated = None
    if session is not None:
        from app.services.algorithm_bridge import reserve_count_for_shift
        from app.db.models import DutyShift as DutyShiftModel
        shift_obj = session.get(DutyShiftModel, s.id)
        if shift_obj is not None:
            calculated = reserve_count_for_shift(session, shift=shift_obj)
    return ShiftOut(
        id=s.id,
        duty_type_id=s.duty_type_id,
        duty_location_id=s.duty_location_id,
        start_date=s.start_date,
        end_date=s.end_date,
        required_count=s.required_count,
        notes=s.notes,
        assigned_count=s.assigned_count,
        reserve_assigned_count=s.reserve_assigned_count,
        fill_status=s.fill_status,
        reserve_count_override=s.reserve_count_override,
        calculated_reserve_count=calculated,
    )


def _load(session: Session, shift_id: uuid.UUID) -> DutyShift:
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return shift


@router.get("", response_model=list[ShiftOut])
def list_shifts(
    date_from: date | None = None,
    date_to: date | None = None,
    duty_type_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ShiftOut]:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    return [_out(s, session) for s in svc.list_shifts(session, date_from=date_from, date_to=date_to, duty_type_id=duty_type_id)]


@router.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(
    body: CreateShiftRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    try:
        shift = svc.create_shift(
            session,
            duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id,
            start_date=body.start_date,
            end_date=body.end_date,
            required_count=body.required_count,
            notes=body.notes,
            reserve_count_override=body.reserve_count_override,
            actor_id=user.id,
        )
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    result = svc.get_shift_fill(session, shift_id=shift.id)
    return _out(result, session)


@router.get("/{shift_id}", response_model=ShiftOut)
def get_shift(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    result = svc.get_shift_fill(session, shift_id=shift_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return _out(result, session)


@router.patch("/{shift_id}", response_model=ShiftOut)
def update_shift(
    shift_id: uuid.UUID,
    body: UpdateShiftRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    extra: dict = {}
    if "notes" in body.model_fields_set:
        extra["notes"] = body.notes
    if "reserve_count_override" in body.model_fields_set:
        extra["reserve_count_override"] = body.reserve_count_override
    if "eligible_node_ids" in body.model_fields_set:
        extra["eligible_node_ids"] = body.eligible_node_ids
    try:
        svc.update_shift(
            session,
            shift=shift,
            start_date=body.start_date,
            end_date=body.end_date,
            required_count=body.required_count,
            actor_id=user.id,
            **extra,
        )
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(svc.get_shift_fill(session, shift_id=shift_id), session)


@router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_shift(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    shift = _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    try:
        svc.delete_shift(session, shift=shift, actor_id=user.id)
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()


class AssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date
    status: str


@router.get("/{shift_id}/assignments", response_model=list[AssignmentOut])
def list_shift_assignments(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AssignmentOut]:
    _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    rows = session.execute(
        select(DutyAssignment).where(DutyAssignment.duty_shift_id == shift_id)
    ).scalars().all()
    return [
        AssignmentOut(
            id=a.id,
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
            status=a.status,
        )
        for a in rows
    ]


@router.delete("/{shift_id}/assignments", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def clear_shift_assignments(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    """Remove all non-cancelled assignments linked to this shift."""
    _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    rows = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.status != "cancelled",
        )
    ).scalars().all()
    for a in rows:
        a.status = "cancelled"
    session.commit()
