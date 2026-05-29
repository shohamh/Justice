from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    Soldier,
    SoldierExemption,
)

_OVERRIDE_REASONS = {"replacement", "no_show_covered", "cancelled", "manual_edit"}


class AssignmentError(Exception):
    """Raised on an invalid assignment operation."""


def _has_overlap(
    session: Session, *, soldier_id: uuid.UUID, start_date: date, end_date: date,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    q = select(DutyAssignment.id).where(
        DutyAssignment.soldier_id == soldier_id,
        DutyAssignment.status != "cancelled",
        DutyAssignment.start_date <= end_date,
        DutyAssignment.end_date >= start_date,
    )
    if exclude_id is not None:
        q = q.where(DutyAssignment.id != exclude_id)
    return session.execute(q).first() is not None


def _has_blocking_exemption(
    session: Session, *, soldier_id: uuid.UUID, duty_type_id: uuid.UUID, start_date: date, end_date: date
) -> bool:
    covering = select(ExemptionDutyTypeMap.exemption_type_id).where(
        ExemptionDutyTypeMap.duty_type_id == duty_type_id
    )
    q = select(SoldierExemption.id).where(
        SoldierExemption.soldier_id == soldier_id,
        SoldierExemption.exemption_type_id.in_(covering),
        SoldierExemption.start_date <= end_date,
        or_(SoldierExemption.end_date.is_(None), SoldierExemption.end_date >= start_date),
    )
    return session.execute(q).first() is not None


def create_assignment(
    session: Session, *, soldier_id: uuid.UUID, duty_type_id: uuid.UUID, duty_location_id: uuid.UUID,
    start_date: date, end_date: date, notes: str | None = None, actor_id: uuid.UUID | None = None,
) -> DutyAssignment:
    if end_date < start_date:
        raise AssignmentError("bad_date_range")
    if session.get(Soldier, soldier_id) is None:
        raise AssignmentError("soldier_not_found")
    if session.get(DutyType, duty_type_id) is None:
        raise AssignmentError("duty_type_not_found")
    if session.get(DutyLocation, duty_location_id) is None:
        raise AssignmentError("location_not_found")
    if _has_overlap(session, soldier_id=soldier_id, start_date=start_date, end_date=end_date):
        raise AssignmentError("overlap")
    if _has_blocking_exemption(session, soldier_id=soldier_id, duty_type_id=duty_type_id,
                               start_date=start_date, end_date=end_date):
        raise AssignmentError("exempted")
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=duty_type_id, duty_location_id=duty_location_id,
        start_date=start_date, end_date=end_date, notes=notes, created_by=actor_id,
    )
    session.add(a)
    session.flush()
    write_audit(session, actor_id=actor_id, action="assignment.create", entity_type="duty_assignment",
                entity_id=a.id, after={"soldier_id": str(soldier_id), "duty_type_id": str(duty_type_id),
                                       "start_date": start_date.isoformat(), "end_date": end_date.isoformat()})
    return a


def cancel_assignment(
    session: Session, *, assignment: DutyAssignment, reason: str, actor_id: uuid.UUID | None = None
) -> DutyAssignment:
    if not reason or not reason.strip():
        raise AssignmentError("reason_required")
    before = {"status": assignment.status}
    assignment.status = "cancelled"
    write_audit(session, actor_id=actor_id, action="assignment.cancel", entity_type="duty_assignment",
                entity_id=assignment.id, before=before, after={"status": "cancelled"},
                context={"reason": reason})
    return assignment
