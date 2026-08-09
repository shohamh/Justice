from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, DutyLocation, DutyType, HierarchyNode, Soldier, SwapRequest
from app.db.session import get_session
from app.services import scoring as scoring_svc
from app.services.calendar_shifts import (
    count_calendar_weapon_ineligible_soldiers,
    get_calendar_shifts,
    get_single_shift,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])


class CalAssignment(BaseModel):
    assignment_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    duty_type_name: str
    duty_location_name: str
    duty_type_color: str


class CalRow(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    hierarchy_node_id: uuid.UUID | None
    assignments: list[CalAssignment]


class CalendarShiftAssigneeDismissal(BaseModel):
    id: uuid.UUID
    dismissed_from: date
    dismissed_to: date
    reason: str | None


class CalendarShiftAssignee(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    hierarchy_label: str | None
    is_reserve: bool
    profile_picture_url: str | None = None
    dismissals: list[CalendarShiftAssigneeDismissal] = []
    reserve_assignment_id: uuid.UUID | None = None
    reserve_hierarchy_distance: int | None = None
    called_up_from: date | None = None
    called_up_to: date | None = None
    primary_assignment_ids: list[uuid.UUID] = []
    hierarchy_path_ids: list[str] = []
    weapon_ineligible: bool = False
    weapon_ineligible_reason: str | None = None


class CalendarShiftOut(BaseModel):
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    duty_type_color: str
    duty_location_name: str
    start_date: date
    end_date: date
    start_time: str
    end_time: str
    start_at: datetime
    end_at: datetime
    required_count: int
    assigned_count: int
    fill_status: str
    reserve_count: int
    assignees: list[CalendarShiftAssignee]
    swap_request_count: int = 0


class CalendarShiftsResponse(BaseModel):
    shifts: list[CalendarShiftOut]


class CalendarWeaponIneligibleCountOut(BaseModel):
    count: int


def _duty_type_color(duty_type_id: uuid.UUID) -> str:
    h = hash(duty_type_id) % 360
    return f"hsl({h}, 65%, 55%)"


def _swap_counts_for_shifts(session: Session, shift_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not shift_ids:
        return {}
    rows = session.execute(
        select(DutyAssignment.duty_shift_id, func.count())
        .select_from(SwapRequest)
        .join(DutyAssignment, DutyAssignment.id == SwapRequest.duty_assignment_id)
        .where(
            DutyAssignment.duty_shift_id.in_(shift_ids),
            SwapRequest.status == "open",
        )
        .group_by(DutyAssignment.duty_shift_id)
    ).all()
    return {shift_id: count for shift_id, count in rows}


def _can_view_assignee_private(
    user: Soldier,
    assignee_soldier_id: uuid.UUID,
    hierarchy_path_ids: list[str],
    roots: set[uuid.UUID],
) -> bool:
    if user.role == "admin" or assignee_soldier_id == user.id:
        return True
    path_uuids = {uuid.UUID(p) for p in hierarchy_path_ids}
    return bool(roots & path_uuids)


def _visible_reason(
    user: Soldier,
    assignee_soldier_id: uuid.UUID,
    hierarchy_path_ids: list[str],
    roots: set[uuid.UUID],
    reason: str | None,
) -> str | None:
    if reason is None:
        return None
    if _can_view_assignee_private(user, assignee_soldier_id, hierarchy_path_ids, roots):
        return reason
    return None


def _redact_shift_reasons(shift: CalendarShiftOut, user: Soldier, roots: set[uuid.UUID]) -> None:
    for assignee in shift.assignees:
        can_view_private = _can_view_assignee_private(
            user, assignee.soldier_id, assignee.hierarchy_path_ids, roots
        )
        if not can_view_private:
            assignee.weapon_ineligible = False
            assignee.weapon_ineligible_reason = None
        for d in assignee.dismissals:
            d.reason = _visible_reason(
                user, assignee.soldier_id, assignee.hierarchy_path_ids, roots, d.reason
            )

@router.get("/shifts/{shift_id}", response_model=CalendarShiftOut)
def get_shift_detail(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CalendarShiftOut:
    raw = get_single_shift(session, shift_id=shift_id)
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    swap_count = _swap_counts_for_shifts(session, [shift_id]).get(shift_id, 0)
    shift = CalendarShiftOut(**raw, swap_request_count=swap_count)
    roots = scope_root_ids(session, user)
    _redact_shift_reasons(shift, user, roots)
    return shift


@router.get("/unit", response_model=list[CalRow])
def unit_calendar(
    node_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[CalRow]:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_READ, target_node=node)
    subtree_node_ids = (
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_id))  # type: ignore[arg-type]
        )
        .scalars()
        .all()
    )
    soldiers = (
        session.execute(
            select(Soldier).where(
                Soldier.hierarchy_node_id.in_(subtree_node_ids), Soldier.left_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    soldier_ids = [s.id for s in soldiers]
    duty_types = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    duty_locations = {
        dl.id: dl.name for dl in session.execute(select(DutyLocation)).scalars().all()
    }
    spans = scoring_svc.effective_duty_spans(
        session, soldier_ids=set(soldier_ids), date_from=date_from, date_to=date_to
    )
    by_soldier: dict[uuid.UUID, list[CalAssignment]] = {sid: [] for sid in soldier_ids}
    for sp in spans:
        dt_id = sp["duty_type_id"]
        dl_id = sp["duty_location_id"]
        by_soldier[sp["soldier_id"]].append(
            CalAssignment(
                assignment_id=sp["assignment_id"],
                duty_type_id=dt_id,
                duty_location_id=dl_id,
                start_date=sp["start_date"],
                end_date=sp["end_date"],
                duty_type_name=duty_types.get(dt_id, ""),
                duty_location_name=duty_locations.get(dl_id, ""),
                duty_type_color=_duty_type_color(dt_id),
            )
        )
    return [
        CalRow(
            soldier_id=s.id,
            full_name=s.full_name,
            hierarchy_node_id=s.hierarchy_node_id,
            assignments=by_soldier[s.id],
        )
        for s in soldiers
    ]


@router.get("/shifts", response_model=CalendarShiftsResponse)
def calendar_shifts(
    node_id: uuid.UUID | None = None,
    soldier_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CalendarShiftsResponse:
    if soldier_id is not None:
        # Personal-calendar view is restricted to the caller's own duties.
        if soldier_id != user.id and user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    elif node_id is not None:
        node = session.get(HierarchyNode, node_id)
        if node is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="node_id_or_soldier_id_required")
    roots = scope_root_ids(session, user)
    raw = get_calendar_shifts(session, node_id=node_id, soldier_id=soldier_id, date_from=date_from, date_to=date_to)
    swap_counts = _swap_counts_for_shifts(session, [s["id"] for s in raw])
    shifts = []
    for s in raw:
        shift = CalendarShiftOut(**s, swap_request_count=swap_counts.get(s["id"], 0))
        _redact_shift_reasons(shift, user, roots)
        shifts.append(shift)
    return CalendarShiftsResponse(shifts=shifts)


@router.get("/weapon-ineligible/count", response_model=CalendarWeaponIneligibleCountOut)
def calendar_weapon_ineligible_count(
    node_id: uuid.UUID | None = None,
    soldier_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CalendarWeaponIneligibleCountOut:
    if soldier_id is not None:
        if soldier_id != user.id and user.role != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    elif node_id is not None:
        node = session.get(HierarchyNode, node_id)
        if node is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
        authorize(session, user, Action.HIERARCHY_READ, target_node=node)
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="node_id_or_soldier_id_required",
        )
    roots = scope_root_ids(session, user)
    visible_soldier_ids: set[uuid.UUID] | None = None
    if user.role != "admin":
        visible_soldier_ids = {user.id}
        visible_soldier_ids.update(
            soldier_id
            for soldier_id, hierarchy_path_ids in session.execute(
                select(Soldier.id, HierarchyNode.path_ids).join(
                    HierarchyNode, Soldier.hierarchy_node_id == HierarchyNode.id
                )
            ).all()
            if roots & set(hierarchy_path_ids or [])
        )
    return CalendarWeaponIneligibleCountOut(
        count=count_calendar_weapon_ineligible_soldiers(
            session,
            node_id=node_id,
            soldier_id=soldier_id,
            date_from=date_from,
            date_to=date_to,
            visible_soldier_ids=visible_soldier_ids,
        )
    )
