from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, _node_in_scope, authorize, is_commander, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import (
    DutyManagerScope,
    HierarchyNode,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeExcusalRequest,
    RangeType,
    Soldier,
)
from app.db.session import get_session
from app.services import range_auto_assign as auto_assign_svc
from app.services import range_excusal as excusal_svc
from app.services import ranges as svc
from app.services.authority import dm_scope_covers_target, range_attendance_edit_authorized
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


def _authorize_range_read(session: Session, user: Soldier, node: HierarchyNode | None) -> bool:
    try:
        authorize(session, user, Action.RANGE_MANAGE, target_node=node)
        return True
    except HTTPException:
        if is_commander(session, user.id) and _node_in_scope(node, scope_root_ids(session, user)):
            return False
        raise


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
    hierarchy_node_id: uuid.UUID | None = None
    range_type: RangeType | None = None
    date: date | None = None
    start_time: str | None = None
    end_time: str | None = None
    location: str | None = None
    required_count: int | None = Field(default=None, ge=0)
    reserve_count: int | None = Field(default=None, ge=0)
    arrival_instructions: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    cancel: bool = False
    cancellation_reason: str | None = None
    force_schedule_change: bool = False


class AddAssignmentBody(BaseModel):
    soldier_id: uuid.UUID
    is_reserve: bool = False


class RangeAssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    is_reserve: bool
    is_draft: bool
    attendance_status: str
    note: str | None


class RangeEventOut(BaseModel):
    start_time: str | None
    end_time: str | None
    arrival_instructions: str | None
    contact_name: str | None
    contact_phone: str | None
    notes: str | None
    id: uuid.UUID
    hierarchy_node_id: uuid.UUID
    range_type: str
    date: date
    location: str
    required_count: int
    reserve_count: int
    status: str
    cancellation_reason: str | None
    assignments: list[RangeAssignmentOut] = []
    primary_filled: int = 0
    reserve_filled: int = 0


def _assignment_out(a: RangeAssignment) -> RangeAssignmentOut:
    return RangeAssignmentOut(
        id=a.id,
        soldier_id=a.soldier_id,
        is_reserve=a.is_reserve,
        is_draft=a.is_draft,
        attendance_status=a.attendance_status,
        note=a.note,
    )


def _event_out(
    session: Session,
    event: RangeEvent,
    *,
    include_assignments: bool = False,
    include_drafts: bool = True,
) -> RangeEventOut:
    query = session.query(RangeAssignment).filter(RangeAssignment.range_event_id == event.id, RangeAssignment.is_draft.is_(False))
    rows = query.all()
    assignments = [_assignment_out(a) for a in rows] if include_assignments else []
    return RangeEventOut(
        id=event.id,
        hierarchy_node_id=event.hierarchy_node_id,
        range_type=event.range_type,
        date=event.date,
        location=event.location,
        required_count=event.required_count,
        start_time=event.start_time,
        end_time=event.end_time,
        arrival_instructions=event.arrival_instructions,
        contact_name=event.contact_name,
        contact_phone=event.contact_phone,
        notes=event.notes,
        reserve_count=event.reserve_count,
        status=event.status,
        cancellation_reason=event.cancellation_reason,
        assignments=assignments,
        primary_filled=sum(not a.is_reserve for a in rows),
        reserve_filled=sum(a.is_reserve for a in rows),
    )


@router.post("", response_model=RangeEventOut, status_code=status.HTTP_201_CREATED)
def create_range_event(
    body: CreateRangeEventBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    target_node = session.get(HierarchyNode, body.hierarchy_node_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=target_node)
    try:
        event = svc.create_range_event(
            session,
            hierarchy_node_id=body.hierarchy_node_id,
            range_type=body.range_type,
            event_date=body.date,
            location=body.location,
            required_count=body.required_count,
            reserve_count=body.reserve_count,
            start_time=body.start_time,
            end_time=body.end_time,
            arrival_instructions=body.arrival_instructions,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            notes=body.notes,
            created_by=user.id,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _event_out(session, event)


@router.patch("/{event_id}", response_model=RangeEventOut)
def update_range_event(
    event_id: uuid.UUID,
    body: UpdateRangeEventBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    if "hierarchy_node_id" in body.model_fields_set:
        new_node = session.get(HierarchyNode, body.hierarchy_node_id)
        authorize(session, user, Action.RANGE_MANAGE, target_node=new_node)
    try:
        if body.cancel:
            event = svc.cancel_range_event(session, event=event, reason=body.cancellation_reason or "", actor_id=user.id)
        else:
            updates = body.model_dump(exclude_unset=True, exclude={"cancel", "cancellation_reason", "force_schedule_change"})
            if "date" in updates:
                updates["event_date"] = updates.pop("date")
            event = svc.update_range_event(session, event=event, actor_id=user.id, force_schedule_change=body.force_schedule_change, **updates)
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _event_out(session, event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_range_event(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        svc.delete_range_event(session, event=event)
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/{event_id}/assignments",
    response_model=RangeAssignmentOut,
    status_code=status.HTTP_201_CREATED,

)
def add_assignment(
    event_id: uuid.UUID,
    body: AddAssignmentBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        assignment = svc.add_range_assignment(
            session,
            event=event,
            soldier_id=body.soldier_id,
            is_reserve=body.is_reserve,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _assignment_out(assignment)


@router.delete("/{event_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment(
    event_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    try:
        svc.remove_range_assignment(session, assignment=assignment, actor_id=user.id)
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{event_id}", response_model=RangeEventOut)
def get_range_event(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    node = _event_node(session, event)
    can_manage = True
    try:
        authorize(session, user, Action.RANGE_MANAGE, target_node=node)
    except HTTPException:
        can_manage = False
        # Commanders get read-only access to this endpoint (roster view), scoped
        # to their own command — mutation routes remain RANGE_MANAGE (DM-only).
        if not (
            is_commander(session, user.id) and _node_in_scope(node, scope_root_ids(session, user))
        ):
            raise
    return _event_out(
        session,
        event,
        include_assignments=True,
        include_drafts=can_manage,
    )


@router.get("", response_model=list[RangeEventOut])
def list_range_events(
    node_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeEventOut]:
    _require_enabled(session)
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    _authorize_range_read(session, user, node)
    query = session.query(RangeEvent).filter(RangeEvent.hierarchy_node_id == node_id)
    if date_from is not None:
        query = query.filter(RangeEvent.date >= date_from)
    if date_to is not None:
        query = query.filter(RangeEvent.date <= date_to)
    events = query.order_by(RangeEvent.date).all()
    return [_event_out(session, e) for e in events]


class RangeExcusalOut(BaseModel):
    id: uuid.UUID
    range_assignment_id: uuid.UUID
    requested_by: uuid.UUID | None
    reason: str
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    promoted_assignment_id: uuid.UUID | None


class ExcuseBody(BaseModel):
    reason: str = Field(min_length=1)


class DecideExcusalBody(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1000)


def _excusal_out(request: RangeExcusalRequest) -> RangeExcusalOut:
    return RangeExcusalOut(
        id=request.id, range_assignment_id=request.range_assignment_id, requested_by=request.requested_by,
        reason=request.reason, status=request.status, decided_by=request.decided_by, decided_at=request.decided_at,
        decision_note=request.decision_note, promoted_assignment_id=request.promoted_assignment_id,
    )

class MarkAttendanceBody(BaseModel):
    status: RangeAttendanceStatus
    note: str | None = Field(default=None, max_length=1000)


@router.patch(
    "/{event_id}/assignments/{assignment_id}/attendance", response_model=RangeAssignmentOut
)
def mark_attendance_route(
    event_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: MarkAttendanceBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    node = _event_node(session, event)
    # See Action.RANGE_ATTENDANCE_EDIT docstring: authorization here is bespoke via
    # range_attendance_edit_authorized (which already short-circuits admins), not authorize().
    if not range_attendance_edit_authorized(session, user=user, target_node=node):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        updated = svc.mark_attendance(
            session,
            assignment=assignment,
            status=body.status,
            marked_by=user.id,
            note=body.note,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _assignment_out(updated)


class AutoAssignResponse(BaseModel):
    created: list[RangeAssignmentOut]
    shortfall: int


@router.post("/{event_id}/auto-assign", response_model=AutoAssignResponse)
def auto_assign(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AutoAssignResponse:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        created, shortfall = auto_assign_svc.propose_range_assignments(session, event=event)
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AutoAssignResponse(created=[_assignment_out(a) for a in created], shortfall=shortfall)


@router.post("/{event_id}/assignments/{assignment_id}/confirm", response_model=RangeAssignmentOut)
def confirm_assignment(
    event_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    try:
        confirmed = auto_assign_svc.confirm_draft_assignment(
            session, assignment=assignment, actor_id=user.id
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _assignment_out(confirmed)


@router.post("/{event_id}/assignments/confirm-all", response_model=list[RangeAssignmentOut])
def confirm_all_assignments(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeAssignmentOut]:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        confirmed = auto_assign_svc.confirm_all_drafts(session, event=event, actor_id=user.id)
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [_assignment_out(a) for a in confirmed]


def _authorize_excusal_decision(session: Session, user: Soldier, event: RangeEvent) -> None:
    node = _event_node(session, event)
    authorize(session, user, Action.RANGE_EXCUSAL_DECIDE, target_node=node)
    if user.role == "admin" or not is_commander(session, user.id):
        return
    dm_roots = session.query(DutyManagerScope).filter_by(duty_manager_id=user.id).all()
    if dm_roots:
        return
    try:
        required_level = str(get_setting(session, "mitvachim.excusal_approve_min_commander_level"))
    except SettingNotFound:
        required_level = "????"
    if not dm_scope_covers_target(
        session, scope_root_ids=scope_root_ids(session, user), target_node=node,
        required_level_key=required_level,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


@router.post("/{event_id}/assignments/{assignment_id}/excuse", response_model=RangeExcusalOut)
def excuse_assignment(
    event_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: ExcuseBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeExcusalOut:
    _require_enabled(session)
    _load_event(session, event_id)
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    if assignment.soldier_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        request = (
            excusal_svc.request_reserve_excusal(
                session, assignment=assignment, reason=body.reason, requested_by=user.id
            ) if assignment.is_reserve else excusal_svc.request_primary_excusal(
                session, assignment=assignment, reason=body.reason, requested_by=user.id
            )
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _excusal_out(request)


@router.get("/{event_id}/excusal-requests", response_model=list[RangeExcusalOut])
def list_excusal_requests(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeExcusalOut]:
    _require_enabled(session)
    event = _load_event(session, event_id)
    _authorize_excusal_decision(session, user, event)
    return [_excusal_out(r) for r in excusal_svc.list_pending_excusal_requests(session, event=event)]


@router.post("/{event_id}/excusal-requests/{request_id}/decide", response_model=RangeExcusalOut)
def decide_excusal_request(
    event_id: uuid.UUID,
    request_id: uuid.UUID,
    body: DecideExcusalBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeExcusalOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    request = session.get(RangeExcusalRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="excusal_request_not_found")
    assignment = session.get(RangeAssignment, request.range_assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="excusal_request_not_found")
    _authorize_excusal_decision(session, user, event)
    try:
        decided = excusal_svc.decide_primary_excusal(
            session, request=request, approve=body.approve, decided_by=user.id, note=body.note
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _excusal_out(decided)