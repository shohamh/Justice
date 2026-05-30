from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyAssignment, DutyShift


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
    fill_status: str  # 'empty' | 'partial' | 'full'


def _fill_status(assigned: int, required: int) -> str:
    if assigned == 0:
        return "empty"
    if assigned >= required:
        return "full"
    return "partial"


def _get_assigned_count(session: Session, shift_id: uuid.UUID) -> int:
    return session.execute(
        select(func.count(DutyAssignment.id)).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).scalar_one()


def _to_with_fill(session: Session, shift: DutyShift) -> ShiftWithFill:
    assigned = _get_assigned_count(session, shift.id)
    return ShiftWithFill(
        id=shift.id,
        duty_type_id=shift.duty_type_id,
        duty_location_id=shift.duty_location_id,
        start_date=shift.start_date,
        end_date=shift.end_date,
        required_count=shift.required_count,
        notes=shift.notes,
        created_by=shift.created_by,
        assigned_count=assigned,
        fill_status=_fill_status(assigned, shift.required_count),
    )


def create_shift(
    session: Session,
    *,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    start_date: date,
    end_date: date,
    required_count: int = 1,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyShift:
    if end_date < start_date:
        raise ShiftError("end_before_start")
    if required_count < 1:
        raise ShiftError("invalid_required_count")
    shift = DutyShift(
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=start_date,
        end_date=end_date,
        required_count=required_count,
        notes=notes,
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
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyShift:
    before: dict = {
        "start_date": shift.start_date.isoformat(),
        "end_date": shift.end_date.isoformat(),
        "required_count": shift.required_count,
        "notes": shift.notes,
    }
    if start_date is not None:
        shift.start_date = start_date
    if end_date is not None:
        shift.end_date = end_date
    if required_count is not None:
        if required_count < 1:
            raise ShiftError("invalid_required_count")
        shift.required_count = required_count
    if notes is not None:
        shift.notes = notes
    if shift.end_date < shift.start_date:
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
        q = q.where(DutyShift.end_date >= date_from)
    if date_to is not None:
        q = q.where(DutyShift.start_date <= date_to)
    if duty_type_id is not None:
        q = q.where(DutyShift.duty_type_id == duty_type_id)
    q = q.order_by(DutyShift.start_date)
    shifts = session.execute(q).scalars().all()
    return [_to_with_fill(session, s) for s in shifts]


def get_shift_fill(session: Session, *, shift_id: uuid.UUID) -> ShiftWithFill | None:
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        return None
    return _to_with_fill(session, shift)
