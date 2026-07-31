from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, RangeAssignment, RangeEvent, RangeType, Soldier
from app.db.session import get_session
from app.services import ranges as svc
from app.services.settings_loader import SettingNotFound, get_setting

router = APIRouter(prefix="/ranges", tags=["ranges"])


def _mitvachim_enabled(session: Session) -> bool:
    try:
        return bool(get_setting(session, "mitvachim.enabled"))
    except SettingNotFound:
        return False


def _require_enabled(session: Session) -> None:
    if not _mitvachim_enabled(session):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


def _event_node(session: Session, event: RangeEvent) -> HierarchyNode | None:
    return session.get(HierarchyNode, event.hierarchy_node_id)


def _load_event(session: Session, event_id: uuid.UUID) -> RangeEvent:
    event = session.get(RangeEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="range_event_not_found")
    return event


class CreateRangeEventBody(BaseModel):
    hierarchy_node_id: uuid.UUID
    range_type: RangeType
    date: date
    location: str = Field(min_length=1)
    required_count: int = Field(ge=0)
    reserve_count: int = Field(default=0, ge=0)
    start_time: str | None = None
    end_time: str | None = None
    arrival_instructions: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None


class UpdateRangeEventBody(BaseModel):
    location: str | None = None
    required_count: int | None = Field(default=None, ge=0)
    reserve_count: int | None = Field(default=None, ge=0)
    arrival_instructions: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    cancel: bool = False


class AddAssignmentBody(BaseModel):
    soldier_id: uuid.UUID
    is_reserve: bool = False


class RangeAssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    is_reserve: bool
    attendance_status: str
    note: str | None


class RangeEventOut(BaseModel):
    id: uuid.UUID
    hierarchy_node_id: uuid.UUID
    range_type: str
    date: date
    location: str
    required_count: int
    reserve_count: int
    status: str
    assignments: list[RangeAssignmentOut] = []


def _assignment_out(a: RangeAssignment) -> RangeAssignmentOut:
    return RangeAssignmentOut(
        id=a.id, soldier_id=a.soldier_id, is_reserve=a.is_reserve,
        attendance_status=a.attendance_status, note=a.note,
    )


def _event_out(session: Session, event: RangeEvent, *, include_assignments: bool = False) -> RangeEventOut:
    assignments: list[RangeAssignmentOut] = []
    if include_assignments:
        rows = session.query(RangeAssignment).filter(RangeAssignment.range_event_id == event.id).all()
        assignments = [_assignment_out(a) for a in rows]
    return RangeEventOut(
        id=event.id, hierarchy_node_id=event.hierarchy_node_id, range_type=event.range_type,
        date=event.date, location=event.location, required_count=event.required_count,
        reserve_count=event.reserve_count, status=event.status, assignments=assignments,
    )


@router.post("", response_model=RangeEventOut, status_code=status.HTTP_201_CREATED)
def create_range_event(
    body: CreateRangeEventBody, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    target_node = session.get(HierarchyNode, body.hierarchy_node_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=target_node)
    try:
        event = svc.create_range_event(
            session, hierarchy_node_id=body.hierarchy_node_id, range_type=body.range_type,
            event_date=body.date, location=body.location, required_count=body.required_count,
            reserve_count=body.reserve_count, start_time=body.start_time, end_time=body.end_time,
            arrival_instructions=body.arrival_instructions, contact_name=body.contact_name,
            contact_phone=body.contact_phone, notes=body.notes, created_by=user.id,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _event_out(session, event)


@router.patch("/{event_id}", response_model=RangeEventOut)
def update_range_event(
    event_id: uuid.UUID, body: UpdateRangeEventBody, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        if body.cancel:
            event = svc.cancel_range_event(session, event=event)
        else:
            event = svc.update_range_event(
                session, event=event, location=body.location, required_count=body.required_count,
                reserve_count=body.reserve_count, arrival_instructions=body.arrival_instructions,
                contact_name=body.contact_name, contact_phone=body.contact_phone, notes=body.notes,
            )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _event_out(session, event)


@router.post("/{event_id}/assignments", response_model=RangeAssignmentOut, status_code=status.HTTP_201_CREATED)
def add_assignment(
    event_id: uuid.UUID, body: AddAssignmentBody, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        assignment = svc.add_range_assignment(
            session, event=event, soldier_id=body.soldier_id, is_reserve=body.is_reserve,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _assignment_out(assignment)


@router.delete("/{event_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment(
    event_id: uuid.UUID, assignment_id: uuid.UUID, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    svc.remove_range_assignment(session, assignment=assignment)


@router.get("/{event_id}", response_model=RangeEventOut)
def get_range_event(
    event_id: uuid.UUID, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    return _event_out(session, event, include_assignments=True)


@router.get("", response_model=list[RangeEventOut])
def list_range_events(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed),
) -> list[RangeEventOut]:
    _require_enabled(session)
    events = session.query(RangeEvent).order_by(RangeEvent.date).all()
    return [_event_out(session, e) for e in events]
