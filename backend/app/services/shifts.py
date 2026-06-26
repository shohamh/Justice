from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit

from app.db.models import DutyAssignment, DutyShift, DutyType

_UNSET = object()


class ShiftError(Exception):
    """Raised on invalid shift operations."""


@dataclass
class ShiftWithFill:
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int
    notes: str | None
    created_by: uuid.UUID | None
    assigned_count: int
    reserve_assigned_count: int
    fill_status: str  # 'empty' | 'partial' | 'full'
    status: str = "active"  # 'active' | 'cancelled'
    reserve_count_override: int | None = None
    eligible_node_ids: list[uuid.UUID] | None = None


def _expected_reserve(shift: DutyShift, duty_type: DutyType | None) -> int:
    if shift.reserve_count_override is not None:
        return shift.reserve_count_override
    if duty_type is None:
        return 0
    ratio = float(duty_type.reserve_ratio or 0)
    minimum = int(duty_type.reserve_minimum or 0)
    return max(minimum, math.ceil(shift.required_count * ratio))


def _fill_status(primary: int, required: int, reserve_assigned: int = 0, reserve_required: int = 0) -> str:
    if primary == 0 and reserve_assigned == 0:
        return "empty"
    if primary >= required and (reserve_required == 0 or reserve_assigned >= reserve_required):
        return "full"
    return "partial"


def _get_assigned_counts(session: Session, shift_id: uuid.UUID) -> tuple[int, int]:
    row = session.execute(
        select(
            func.count(DutyAssignment.id).label("total"),
            func.sum(case((DutyAssignment.is_reserve == True, 1), else_=0)).label("reserve"),
        ).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).one()
    total = row.total or 0
    reserve = row.reserve or 0
    return total, reserve


def _to_with_fill(session: Session, shift: DutyShift) -> ShiftWithFill:
    total, reserve = _get_assigned_counts(session, shift.id)
    primary = total - reserve
    duty_type = session.get(DutyType, shift.duty_type_id)
    exp_reserve = _expected_reserve(shift, duty_type)
    return ShiftWithFill(
        id=shift.id,
        duty_type_id=shift.duty_type_id,
        duty_location_id=shift.duty_location_id,
        start_date=shift.start_date,
        end_date=shift.end_date,
        required_count=shift.required_count,
        notes=shift.notes,
        created_by=shift.created_by,
        assigned_count=primary,
        reserve_assigned_count=reserve,
        fill_status=_fill_status(primary, shift.required_count, reserve, exp_reserve),
        status=shift.status,
        reserve_count_override=shift.reserve_count_override,
        eligible_node_ids=shift.eligible_node_ids,
    )


def create_shift(
    session: Session,
    *,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    start_date: date,
    end_date: date,
    start_time: str = "00:00",
    end_time: str = "23:59",
    required_count: int = 1,
    notes: str | None = None,
    reserve_count_override: int | None = None,
    eligible_node_ids: list[uuid.UUID] | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyShift:
    if end_date <= start_date:
        raise ShiftError("end_before_start")
    if required_count < 1:
        raise ShiftError("invalid_required_count")
    for t in (start_time, end_time):
        parts = t.split(":")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise ShiftError("invalid_time")
    if (end_date - start_date).days == 1 and end_time <= start_time:
        raise ShiftError("invalid_time_order")
    shift = DutyShift(
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        required_count=required_count,
        notes=notes,
        reserve_count_override=reserve_count_override,
        eligible_node_ids=eligible_node_ids,
        created_by=actor_id,
    )
    session.add(shift)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_shift.create",
        entity_type="duty_shift",
        entity_id=shift.id,
        after={
            "duty_type_id": str(duty_type_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "required_count": required_count,
        },
    )
    return shift


def update_shift(
    session: Session,
    *,
    shift: DutyShift,
    start_date: date | None = None,
    end_date: date | None = None,
    required_count: int | None = None,
    notes: object = _UNSET,  # use sentinel to allow explicit null (clearing notes)
    reserve_count_override: object = _UNSET,  # sentinel to allow explicit null (clearing override)
    eligible_node_ids: object = _UNSET,  # sentinel to allow explicit null (clearing eligible nodes)
    actor_id: uuid.UUID | None = None,
) -> DutyShift:
    before: dict = {
        "start_date": shift.start_date.isoformat(),
        "end_date": shift.end_date.isoformat(),
        "required_count": shift.required_count,
        "notes": shift.notes,
        "reserve_count_override": shift.reserve_count_override,
        "eligible_node_ids": shift.eligible_node_ids,
    }
    if start_date is not None:
        shift.start_date = start_date
    if end_date is not None:
        shift.end_date = end_date
    if required_count is not None:
        if required_count < 1:
            raise ShiftError("invalid_required_count")
        shift.required_count = required_count
    if notes is not _UNSET:
        shift.notes = notes  # type: ignore[assignment]  # None means clear
    if reserve_count_override is not _UNSET:
        shift.reserve_count_override = reserve_count_override  # type: ignore[assignment]  # None means clear
    if eligible_node_ids is not _UNSET:
        shift.eligible_node_ids = eligible_node_ids  # type: ignore[assignment]  # None means clear
    if shift.end_date <= shift.start_date:
        raise ShiftError("end_before_start")
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_shift.update",
        entity_type="duty_shift",
        entity_id=shift.id,
        before=before,
        after={
            "start_date": shift.start_date.isoformat(),
            "end_date": shift.end_date.isoformat(),
            "required_count": shift.required_count,
            "notes": shift.notes,
            "reserve_count_override": shift.reserve_count_override,
            "eligible_node_ids": shift.eligible_node_ids,
        },
    )
    return shift


def delete_shift(
    session: Session,
    *,
    shift: DutyShift,
    actor_id: uuid.UUID | None = None,
) -> None:
    published_count = session.execute(
        select(func.count(DutyAssignment.id)).where(
            DutyAssignment.duty_shift_id == shift.id,
            DutyAssignment.status == "published",
        )
    ).scalar_one()
    if published_count > 0:
        raise ShiftError("has_assignments")
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_shift.delete",
        entity_type="duty_shift",
        entity_id=shift.id,
        before={"start_date": shift.start_date.isoformat(), "end_date": shift.end_date.isoformat()},
    )
    session.delete(shift)


def list_shifts(
    session: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    duty_type_id: uuid.UUID | None = None,
) -> list[ShiftWithFill]:
    q = select(DutyShift)
    if date_from is not None:
        q = q.where(DutyShift.end_date > date_from)
    if date_to is not None:
        q = q.where(DutyShift.start_date <= date_to)
    if duty_type_id is not None:
        q = q.where(DutyShift.duty_type_id == duty_type_id)
    q = q.order_by(DutyShift.start_date)
    shifts = session.execute(q).scalars().all()
    if not shifts:
        return []

    shift_ids = [s.id for s in shifts]
    count_rows = session.execute(
        select(
            DutyAssignment.duty_shift_id,
            func.count(DutyAssignment.id).label("cnt"),
            func.sum(case((DutyAssignment.is_reserve == True, 1), else_=0)).label("reserve_cnt"),
        )
        .where(
            DutyAssignment.duty_shift_id.in_(shift_ids),
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
        .group_by(DutyAssignment.duty_shift_id)
    ).all()
    count_map: dict[uuid.UUID, int] = {row.duty_shift_id: row.cnt for row in count_rows}
    reserve_map: dict[uuid.UUID, int] = {row.duty_shift_id: row.reserve_cnt or 0 for row in count_rows}

    duty_type_ids = list({s.duty_type_id for s in shifts})
    duty_types = {
        dt.id: dt
        for dt in session.execute(select(DutyType).where(DutyType.id.in_(duty_type_ids))).scalars().all()
    }

    result = []
    for shift in shifts:
        total_assigned = count_map.get(shift.id, 0)
        reserve_assigned = reserve_map.get(shift.id, 0)
        primary_assigned = total_assigned - reserve_assigned
        exp_reserve = _expected_reserve(shift, duty_types.get(shift.duty_type_id))
        result.append(ShiftWithFill(
            id=shift.id,
            duty_type_id=shift.duty_type_id,
            duty_location_id=shift.duty_location_id,
            start_date=shift.start_date,
            end_date=shift.end_date,
            required_count=shift.required_count,
            notes=shift.notes,
            created_by=shift.created_by,
            assigned_count=primary_assigned,
            reserve_assigned_count=reserve_assigned,
            fill_status=_fill_status(primary_assigned, shift.required_count, reserve_assigned, exp_reserve),
            status=shift.status,
            reserve_count_override=shift.reserve_count_override,
        ))
    return result


def get_shift_fill(session: Session, *, shift_id: uuid.UUID) -> ShiftWithFill | None:
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        return None
    return _to_with_fill(session, shift)
