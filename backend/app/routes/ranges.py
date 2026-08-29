from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.authz import (
    Action, _node_in_scope, authorize, is_commander, is_duty_manager,
    responsible_range_manager_authorized, scope_root_ids,
)
from app.auth.deps import require_password_changed
from app.db.models import (
    DutyManagerScope,
    HierarchyNode,
    RangeAssignment,
    RangeAssignmentRequest,
    RangeAttendanceStatus,
    RangeEvent,
    RangeExcusalRequest,
    RangeType,
    Soldier,
)
from app.db.session import get_session
from app.services import range_auto_assign as auto_assign_svc
from app.services import range_excusal as excusal_svc
from app.services import range_assignment_requests as assignment_request_svc
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


def _authorize_range_manage(session: Session, user: Soldier, event: RangeEvent) -> None:
    try:
        authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    except HTTPException:
        if not responsible_range_manager_authorized(
            session, user=user, responsible_duty_manager_id=event.responsible_duty_manager_id,
        ):
            raise


class CreateRangeEventBody(BaseModel):
    hierarchy_node_id: uuid.UUID
    range_type: RangeType
    date: date_type
    range_location_id: uuid.UUID
    required_count: int = Field(ge=0)
    reserve_count: int = Field(default=0, ge=0)
    start_time: str | None = None
    end_time: str | None = None
    arrival_instructions: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    responsible_duty_manager_id: uuid.UUID | None = None


class UpdateRangeEventBody(BaseModel):
    hierarchy_node_id: uuid.UUID | None = None
    range_type: RangeType | None = None
    date: date_type | None = None
    start_time: str | None = None
    end_time: str | None = None
    range_location_id: uuid.UUID | None = None
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
    assignment_reason_code: str = Field(default="manual", min_length=1, max_length=100)
    assignment_reason_text: str | None = Field(default="שיבוץ ידני", max_length=1000)
    override_reason: str | None = Field(default=None, max_length=1000)


class RangeAssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    is_reserve: bool
    is_draft: bool
    attendance_status: str
    note: str | None
    assignment_reason_code: str | None
    assignment_reason_text: str | None


class RangeAssignmentRequestBody(BaseModel):
    soldier_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason must not be empty")
        return value


class RangeAssignmentRequestOut(BaseModel):
    id: uuid.UUID
    range_event_id: uuid.UUID
    soldier_id: uuid.UUID
    requested_by: uuid.UUID
    reason: str
    system_reason_code: str | None
    system_reason_text: str | None
    status: str
    approved_assignment_id: uuid.UUID | None = None


def _assignment_request_out(request: RangeAssignmentRequest) -> RangeAssignmentRequestOut:
    return RangeAssignmentRequestOut(
        id=request.id,
        range_event_id=request.range_event_id,
        soldier_id=request.soldier_id,
        requested_by=request.requested_by,
        reason=request.reason,
        system_reason_code=request.system_reason_code,
        system_reason_text=request.system_reason_text,
        status=request.status,
        approved_assignment_id=request.approved_assignment_id,
    )


class ApproveRangeAssignmentRequestBody(BaseModel):
    is_reserve: bool


@router.post(
    "/{event_id}/assignment-requests",
    response_model=RangeAssignmentRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def create_assignment_request(
    event_id: uuid.UUID,
    body: RangeAssignmentRequestBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentRequestOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    try:
        request = assignment_request_svc.create_assignment_request(
            session,
            event=event,
            soldier_id=body.soldier_id,
            requested_by=user,
            reason=body.reason,
        )
    except assignment_request_svc.RangeAssignmentRequestError as exc:
        detail = str(exc)
        if detail == "soldier_outside_scope":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden") from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc
    return _assignment_request_out(request)


@router.patch(
    "/{event_id}/assignment-requests/{request_id}/approve",
    response_model=RangeAssignmentOut,
)
def approve_assignment_request(
    event_id: uuid.UUID,
    request_id: uuid.UUID,
    body: ApproveRangeAssignmentRequestBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    request = session.get(RangeAssignmentRequest, request_id)
    if request is None or request.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    try:
        assignment = assignment_request_svc.approve_assignment_request(
            session, request=request, actor=user, is_reserve=body.is_reserve,
        )
    except assignment_request_svc.RangeAssignmentRequestError as exc:
        detail = str(exc)
        code = status.HTTP_403_FORBIDDEN if detail == "not_responsible_manager" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from exc
    return _assignment_out(assignment)


class FoodSpecialConstraintOut(BaseModel):
    soldier_id: uuid.UUID
    soldier_name: str
    food_type: str
    constraint: str


class FoodAssignmentSummaryOut(BaseModel):
    counts: dict[str, int]
    special_constraints: list[FoodSpecialConstraintOut]


class FoodSummaryOut(BaseModel):
    primary: FoodAssignmentSummaryOut
    reserve: FoodAssignmentSummaryOut


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
    date: date_type
    range_location_id: uuid.UUID
    location: str
    required_count: int
    reserve_count: int
    status: str
    cancellation_reason: str | None
    assignments: list[RangeAssignmentOut] = []
    primary_filled: int = 0
    reserve_filled: int = 0
    assigned_to_me: bool = False
    can_edit_attendance: bool = False
    food_summary: FoodSummaryOut | None = None
    responsible_duty_manager_id: uuid.UUID | None = None


def _assignment_out(a: RangeAssignment) -> RangeAssignmentOut:
    return RangeAssignmentOut(
        id=a.id,
        soldier_id=a.soldier_id,
        is_reserve=a.is_reserve,
        is_draft=a.is_draft,
        attendance_status=a.attendance_status,
        note=a.note,
        assignment_reason_code=a.assignment_reason_code,
        assignment_reason_text=a.assignment_reason_text,
    )


def _food_summary(session: Session, rows: list[RangeAssignment]) -> FoodSummaryOut:
    allowed_types = ("regular", "vegetarian", "vegan", "gluten_free", "kosher_le_mehadrin")

    def summarize(assignments: list[RangeAssignment]) -> FoodAssignmentSummaryOut:
        counts = {food_type: 0 for food_type in allowed_types}
        counts["unspecified"] = 0
        special_constraints: list[FoodSpecialConstraintOut] = []
        for assignment in assignments:
            soldier = session.get(Soldier, assignment.soldier_id)
            if soldier is None:
                continue
            counts[soldier.food_type or "unspecified"] += 1
            if soldier.food_constraints and soldier.food_constraints.strip():
                special_constraints.append(FoodSpecialConstraintOut(
                    soldier_id=soldier.id,
                    soldier_name=soldier.full_name,
                    food_type=soldier.food_type or "unspecified",
                    constraint=soldier.food_constraints.strip(),
                ))
        return FoodAssignmentSummaryOut(counts=counts, special_constraints=special_constraints)

    confirmed = [assignment for assignment in rows if not assignment.is_draft]
    return FoodSummaryOut(
        primary=summarize([a for a in confirmed if not a.is_reserve]),
        reserve=summarize([a for a in confirmed if a.is_reserve]),
    )


def _event_out(
    session: Session,
    event: RangeEvent,
    *,
    user: Soldier,
    include_assignments: bool = False,
    include_drafts: bool = True,
    include_food_summary: bool = False,
) -> RangeEventOut:
    query = session.query(RangeAssignment).filter(RangeAssignment.range_event_id == event.id)
    if not include_drafts:
        query = query.filter(RangeAssignment.is_draft.is_(False))
    rows = query.all()
    confirmed_rows = [a for a in rows if not a.is_draft]
    assignments = [_assignment_out(a) for a in rows] if include_assignments else []
    node = _event_node(session, event)
    from app.db.models import RangeLocation
    location = session.get(RangeLocation, event.range_location_id)
    location_name = location.name if location else ""
    assigned_to_me = any(assignment.soldier_id == user.id for assignment in rows)
    can_edit_attendance = node is not None and range_attendance_edit_authorized(
        session, user=user, target_node=node,
    )
    return RangeEventOut(
        id=event.id,
        hierarchy_node_id=event.hierarchy_node_id,
        range_type=event.range_type,
        date=event.date,
        range_location_id=event.range_location_id,
        location=location_name,
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
        primary_filled=sum(not a.is_reserve for a in confirmed_rows),
        reserve_filled=sum(a.is_reserve for a in confirmed_rows),
        assigned_to_me=assigned_to_me,
        can_edit_attendance=can_edit_attendance,
        food_summary=_food_summary(session, rows) if include_food_summary else None,
        responsible_duty_manager_id=event.responsible_duty_manager_id,
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
            range_location_id=body.range_location_id,
            required_count=body.required_count,
            reserve_count=body.reserve_count,
            start_time=body.start_time,
            end_time=body.end_time,
            arrival_instructions=body.arrival_instructions,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            notes=body.notes,
            created_by=user.id,
            responsible_duty_manager_id=body.responsible_duty_manager_id,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _event_out(session, event, user=user)


@router.patch("/{event_id}", response_model=RangeEventOut)
def update_range_event(
    event_id: uuid.UUID,
    body: UpdateRangeEventBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    _authorize_range_manage(session, user, event)
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
    return _event_out(session, event, user=user)


@router.delete("/{event_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
def delete_range_event(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    _require_enabled(session)
    event = _load_event(session, event_id)
    _authorize_range_manage(session, user, event)
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
    _authorize_range_manage(session, user, event)
    try:
        assignment = svc.add_range_assignment(
            session,
            event=event,
            soldier_id=body.soldier_id,
            is_reserve=body.is_reserve,
            assignment_reason_code=body.assignment_reason_code.strip(),
            assignment_reason_text=(
                body.assignment_reason_text.strip() if body.assignment_reason_text is not None else None
            ),
            user=user,
            override_reason=body.override_reason,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _assignment_out(assignment)


class BatchAssignBody(BaseModel):
    primaries: list[uuid.UUID] = []
    reserves: list[uuid.UUID] = []
    override_reason: str | None = Field(default=None, max_length=1000)


@router.post("/{event_id}/assignments/batch", response_model=list[RangeAssignmentOut])
def batch_assign(
    event_id: uuid.UUID,
    body: BatchAssignBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeAssignmentOut]:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        created = svc.assign_batch(
            session, event=event,
            primary_soldier_ids=body.primaries, reserve_soldier_ids=body.reserves,
            actor_id=user.id, user=user, override_reason=body.override_reason,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [_assignment_out(a) for a in created]


class UpdateAssignmentReasonBody(BaseModel):
    assignment_reason_code: str = Field(min_length=1, max_length=100)
    assignment_reason_text: str | None = Field(default=None, max_length=1000)


@router.patch(
    "/{event_id}/assignments/{assignment_id}/reason", response_model=RangeAssignmentOut
)
def update_assignment_reason(
    event_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: UpdateAssignmentReasonBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    reason_code = body.assignment_reason_code.strip()
    reason_text = body.assignment_reason_text.strip() if body.assignment_reason_text is not None else None
    if not reason_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="assignment_reason_code_required")
    if reason_code == "custom" and not reason_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="custom_reason_text_required")
    before = {
        "assignment_reason_code": assignment.assignment_reason_code,
        "assignment_reason_text": assignment.assignment_reason_text,
    }
    assignment.assignment_reason_code = reason_code
    assignment.assignment_reason_text = reason_text
    write_audit(
        session,
        actor_id=user.id,
        action="range_assignment_reason_update",
        entity_type="range_assignment",
        entity_id=assignment.id,
        before=before,
        after={
            "assignment_reason_code": reason_code,
            "assignment_reason_text": reason_text,
        },
    )
    session.commit()
    session.refresh(assignment)
    return _assignment_out(assignment)


@router.delete(
    "/{event_id}/assignments/{assignment_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_assignment(
    event_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: RemoveAssignmentBody,
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
        svc.remove_range_assignment(session, assignment=assignment, reason=body.reason, actor_id=user.id)
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
    if svc.mark_past_range_events_completed(session):
        session.commit()
    return _event_out(
        session,
        event,
        user=user,
        include_assignments=True,
        include_drafts=can_manage,
        include_food_summary=user.role == "admin" or is_duty_manager(session, user.id),
    )


@router.get("", response_model=list[RangeEventOut])
def list_range_events(
    node_id: str | None = None,
    soldier_id: uuid.UUID | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeEventOut]:
    _require_enabled(session)
    if soldier_id is not None:
        # Personal view: only this soldier's own range events, regardless of
        # hierarchy — a range can be created at a node outside the soldier's
        # own subtree while they're still assigned to it.
        if soldier_id != user.id and user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        query = (
            session.query(RangeEvent)
            .join(RangeAssignment, RangeAssignment.range_event_id == RangeEvent.id)
            .filter(RangeAssignment.soldier_id == soldier_id)
        )
        can_manage = False
    else:
        if node_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="node_id_required")
        if node_id == "None":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        try:
            node_uuid = uuid.UUID(node_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_node_id") from exc
        node = session.get(HierarchyNode, node_uuid)
        if node is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        can_manage = _authorize_range_read(session, user, node)
        subtree_node_ids = (
            session.execute(
                select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_uuid))  # type: ignore[arg-type]
            )
            .scalars()
            .all()
        )
        query = session.query(RangeEvent).filter(RangeEvent.hierarchy_node_id.in_(subtree_node_ids))
    if svc.mark_past_range_events_completed(session):
        session.commit()
    if date_from is not None:
        query = query.filter(RangeEvent.date >= date_from)
    if date_to is not None:
        query = query.filter(RangeEvent.date <= date_to)
    events = query.order_by(RangeEvent.date).all()
    return [_event_out(session, e, user=user, include_drafts=can_manage) for e in events]


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


class RemoveAssignmentBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason must not be empty")
        return v


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


class RangeCandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    personal_number: str
    reason_code: str
    explanation: str
    conflict_warning: str | None = None
    personal_constraint_conflict: bool = False


class ExcludedSoldierOut(BaseModel):
    soldier_id: uuid.UUID
    soldier_name: str
    reason: str


class RangeCandidatesOut(BaseModel):
    candidates: list[RangeCandidateOut]
    excluded: list[ExcludedSoldierOut]


@router.get("/{event_id}/candidates", response_model=RangeCandidatesOut)
def get_range_candidates(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeCandidatesOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    ranked, excluded = auto_assign_svc.rank_candidates_with_excluded(session, event=event, user=user)
    excluded_soldiers_by_id = {
        s.id: s
        for s in session.execute(
            select(Soldier).where(Soldier.id.in_([x.soldier_id for x in excluded]))
        ).scalars().all()
    } if excluded else {}
    return RangeCandidatesOut(
        candidates=[
            RangeCandidateOut(
                soldier_id=c.soldier.id, full_name=c.soldier.full_name, personal_number=c.soldier.personal_number,
                reason_code=c.reason_code, explanation=c.explanation, conflict_warning=c.conflict_warning,
                personal_constraint_conflict=c.personal_constraint_conflict,
            )
            for c in ranked
        ],
        excluded=[
            ExcludedSoldierOut(
                soldier_id=x.soldier_id,
                soldier_name=excluded_soldiers_by_id[x.soldier_id].full_name
                if x.soldier_id in excluded_soldiers_by_id else str(x.soldier_id),
                reason=x.reason,
            )
            for x in excluded
        ],
    )


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
        required_level = "group"  # seeded key for מדור — get_level_rank matches .key, not .label
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
