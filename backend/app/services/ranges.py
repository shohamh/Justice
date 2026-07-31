from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    HierarchyNode,
    NotificationType,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeEventStatus,
    RangeType,
    Soldier,
    SoldierRangeQualification,
)
from app.services.adjustments import create_adjustment
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting


class RangeValidationError(Exception):
    pass


def create_range_event(
    session: Session,
    *,
    hierarchy_node_id: uuid.UUID,
    range_type: RangeType,
    event_date: date,
    location: str,
    required_count: int,
    reserve_count: int = 0,
    start_time: str | None = None,
    end_time: str | None = None,
    arrival_instructions: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> RangeEvent:
    if session.get(HierarchyNode, hierarchy_node_id) is None:
        raise RangeValidationError("hierarchy_node_not_found")
    if required_count < 0 or reserve_count < 0:
        raise RangeValidationError("counts_must_be_non_negative")

    event = RangeEvent(
        hierarchy_node_id=hierarchy_node_id,
        range_type=range_type,
        date=event_date,
        location=location,
        required_count=required_count,
        reserve_count=reserve_count,
        start_time=start_time,
        end_time=end_time,
        arrival_instructions=arrival_instructions,
        contact_name=contact_name,
        contact_phone=contact_phone,
        notes=notes,
        created_by=created_by,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def update_range_event(
    session: Session,
    *,
    event: RangeEvent,
    location: str | None = None,
    arrival_instructions: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    required_count: int | None = None,
    reserve_count: int | None = None,
    notes: str | None = None,
) -> RangeEvent:
    if required_count is not None:
        if required_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        event.required_count = required_count
    if reserve_count is not None:
        if reserve_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        event.reserve_count = reserve_count
    if location is not None:
        event.location = location
    if arrival_instructions is not None:
        event.arrival_instructions = arrival_instructions
    if contact_name is not None:
        event.contact_name = contact_name
    if contact_phone is not None:
        event.contact_phone = contact_phone
    if notes is not None:
        event.notes = notes
    session.commit()
    session.refresh(event)
    return event


def cancel_range_event(session: Session, *, event: RangeEvent) -> RangeEvent:
    event.status = RangeEventStatus.cancelled
    session.commit()
    session.refresh(event)
    return event


from app.services.range_exemption import is_range_exempt


def add_range_assignment(
    session: Session, *, event: RangeEvent, soldier_id: uuid.UUID, is_reserve: bool,
) -> RangeAssignment:
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise RangeValidationError("soldier_not_found")
    node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    event_node = session.get(HierarchyNode, event.hierarchy_node_id)
    if node is None or event_node is None or event.hierarchy_node_id not in node.path_ids:
        raise RangeValidationError("soldier_outside_event_subunit")
    if is_range_exempt(session, soldier=soldier, event_date=event.date):
        raise RangeValidationError("soldier_range_exempt")

    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier_id, is_reserve=is_reserve)
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def remove_range_assignment(session: Session, *, assignment: RangeAssignment) -> None:
    session.delete(assignment)
    session.commit()


_VALIDITY_SETTING_KEYS: dict[str, str] = {
    RangeType.laser: "mitvachim.laser_validity_days",
    RangeType.live: "mitvachim.live_validity_days",
    RangeType.alal: "mitvachim.alal_validity_days",
}
_NO_SHOW_PENALTY = Decimal("-1")


def _validity_days(session: Session, range_type: str) -> int:
    key = _VALIDITY_SETTING_KEYS[range_type]
    try:
        value = get_setting(session, key)
    except SettingNotFound:
        return 180
    return int(value)


def _record_qualification(session: Session, *, soldier_id: uuid.UUID, range_type: str, valid_until: date,
                           source_range_assignment_id: uuid.UUID) -> None:
    session.add(SoldierRangeQualification(
        soldier_id=soldier_id, range_type=range_type, valid_until=valid_until,
        source_range_assignment_id=source_range_assignment_id,
    ))


def get_effective_range_qualification(session: Session, *, soldier_id: uuid.UUID, range_type: str) -> date | None:
    """Returns the soldier's current valid_until for range_type (the furthest-out
    valid_until among all non-deleted qualification rows for that soldier/type), or
    None if they have no qualification record at that type."""
    return session.execute(
        select(func.max(SoldierRangeQualification.valid_until)).where(
            SoldierRangeQualification.soldier_id == soldier_id,
            SoldierRangeQualification.range_type == range_type,
        )
    ).scalar_one_or_none()


def _delete_qualification_from_this_assignment(session: Session, *, assignment: RangeAssignment) -> None:
    existing = session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.source_range_assignment_id == assignment.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        session.delete(existing)


def mark_attendance(
    session: Session, *, assignment: RangeAssignment, status: RangeAttendanceStatus,
    marked_by: uuid.UUID, note: str | None = None,
) -> RangeAssignment:
    event = session.get(RangeEvent, assignment.range_event_id)
    if event is None:
        raise RangeValidationError("event_not_found")
    if event.status == RangeEventStatus.cancelled:
        raise RangeValidationError("event_cancelled")
    if event.date > date.today():
        raise RangeValidationError("event_not_yet_occurred")
    if status == RangeAttendanceStatus.no_show and not note:
        raise RangeValidationError("note_required_for_no_show")

    previous_status = assignment.attendance_status

    # Reverse the previous side effect, if any.
    if previous_status == RangeAttendanceStatus.no_show and assignment.score_adjustment_id is not None:
        create_adjustment(
            session, soldier_id=assignment.soldier_id, delta=Decimal("1"),
            reason="range_no_show_reversed", actor_id=marked_by,
        )
        write_audit(
            session, actor_id=marked_by, action="range_attendance_correction_reverse_no_show",
            entity_type="range_assignment", entity_id=assignment.id,
            before={"attendance_status": previous_status}, after=None,
        )
        assignment.score_adjustment_id = None
    if previous_status == RangeAttendanceStatus.present:
        _delete_qualification_from_this_assignment(session, assignment=assignment)

    # Apply the new side effect.
    if status == RangeAttendanceStatus.present:
        valid_until = event.date + timedelta(days=_validity_days(session, event.range_type))
        _record_qualification(
            session, soldier_id=assignment.soldier_id, range_type=event.range_type,
            valid_until=valid_until, source_range_assignment_id=assignment.id,
        )
    elif status == RangeAttendanceStatus.no_show:
        adjustment = create_adjustment(
            session, soldier_id=assignment.soldier_id, delta=_NO_SHOW_PENALTY,
            reason="range_no_show", actor_id=marked_by,
        )
        assignment.score_adjustment_id = adjustment.id
        create_notification(
            session, soldier_id=assignment.soldier_id, type=NotificationType.no_show_marked,
            title="נרשם היעדרות ממטווח", body=note, reference_type="range_assignment",
            reference_id=assignment.id, actor_id=marked_by,
        )

    assignment.attendance_status = status
    assignment.marked_by = marked_by
    assignment.marked_at = datetime.now(timezone.utc)
    assignment.note = note

    write_audit(
        session, actor_id=marked_by, action="range_attendance_marked", entity_type="range_assignment",
        entity_id=assignment.id, before={"attendance_status": previous_status}, after={"attendance_status": status},
    )

    session.commit()
    session.refresh(assignment)
    return assignment
