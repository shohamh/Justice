from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.audit.writer import write_audit
from app.db.models import (
    HierarchyNode,
    Notification,
    NotificationType,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeEventStatus,
    RangeType,
    ScoreAdjustment,
    Soldier,
    SoldierRangeQualification,
)
from app.services.adjustments import create_adjustment
from app.services.notifications import create_notification, notify_duty_managers_in_scope
from app.services.range_exemption import is_range_exempt
from app.services.settings_loader import SettingNotFound, get_setting


class RangeValidationError(Exception):
    pass

_UNSET = object()


def _mitvachim_enabled(session: Session) -> bool:
    setting = session.get(__import__("app.db.models", fromlist=["SystemSetting"]).SystemSetting, "mitvachim.enabled")
    return setting is None or setting.value is True


def _range_notification(session: Session, **kwargs):
    if _mitvachim_enabled(session):
        return create_notification(session, **kwargs)
    return None


_RANGE_ASSIGNMENT_LOCK_NAMESPACE = 0x52414E47


def _acquire_range_assignment_date_lock(session: Session, *, event_date: date) -> None:
    session.execute(
        select(
            func.pg_advisory_xact_lock(
                _RANGE_ASSIGNMENT_LOCK_NAMESPACE,
                event_date.toordinal(),
            )
        )
    )



def _range_context(event: RangeEvent, *, reason: str | None = None) -> str:
    context = f"date={event.date.isoformat()} | type={event.range_type.value} | location={event.location}"
    return f"{context} | reason={reason}" if reason else context


def _notify_roster_change(
    session: Session, *, event: RangeEvent, soldier_ids: set[uuid.UUID], actor_id: uuid.UUID | None = None,
) -> None:
    assignments = session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    fill = (
        f"primary={sum(1 for a in assignments if not a.is_reserve and not a.is_draft)}/{event.required_count}"
        f" | reserve={sum(1 for a in assignments if a.is_reserve and not a.is_draft)}/{event.reserve_count}"
    )
    for soldier_id in soldier_ids:
        _range_notification(
            session, soldier_id=soldier_id, type=NotificationType.range_roster_changed,
            title="Range roster changed", body=f"{_range_context(event)} | {fill}",
            reference_type="range_event", reference_id=event.id, actor_id=actor_id,
        )
    if soldier_ids and _mitvachim_enabled(session):
        notify_duty_managers_in_scope(session, soldier_id=next(iter(soldier_ids)), type=NotificationType.range_roster_changed, title="Range roster changed", body=f"{_range_context(event)} | {fill}", reference_type="range_event", reference_id=event.id, actor_id=actor_id)

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
    if start_time and end_time and start_time > end_time:
        raise RangeValidationError("start_time_after_end_time")

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
    hierarchy_node_id: uuid.UUID | object = _UNSET,
    range_type: RangeType | object = _UNSET,
    event_date: date | object = _UNSET,
    start_time: str | None | object = _UNSET,
    end_time: str | None | object = _UNSET,
    location: str | object = _UNSET,
    arrival_instructions: str | None | object = _UNSET,
    contact_name: str | None | object = _UNSET,
    contact_phone: str | None | object = _UNSET,
    required_count: int | object = _UNSET,
    reserve_count: int | object = _UNSET,
    notes: str | None | object = _UNSET,
    force_schedule_change: bool = False,
    actor_id: uuid.UUID | None = None,
) -> RangeEvent:
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    assignments_exist = session.query(RangeAssignment.id).filter(
        RangeAssignment.range_event_id == event.id,
        RangeAssignment.is_draft.is_(False),
    ).first() is not None
    schedule_changed = (
        (range_type is not _UNSET and range_type != event.range_type)
        or (event_date is not _UNSET and event_date != event.date)
    )
    if schedule_changed and assignments_exist and not force_schedule_change:
        raise RangeValidationError("schedule_change_confirmation_required")
    proposed_start = event.start_time if start_time is _UNSET else start_time
    proposed_end = event.end_time if end_time is _UNSET else end_time
    if proposed_start and proposed_end and proposed_start > proposed_end:
        raise RangeValidationError("start_time_after_end_time")
    before: dict = {}
    after: dict = {}
    if hierarchy_node_id is not _UNSET:
        if session.get(HierarchyNode, hierarchy_node_id) is None:
            raise RangeValidationError("hierarchy_node_not_found")
        before["hierarchy_node_id"] = str(event.hierarchy_node_id)
        event.hierarchy_node_id = hierarchy_node_id
        after["hierarchy_node_id"] = str(hierarchy_node_id)
    if range_type is not _UNSET:
        before["range_type"] = event.range_type
        event.range_type = range_type
        after["range_type"] = range_type
    if event_date is not _UNSET:
        before["date"] = event.date.isoformat()
        event.date = event_date
        after["date"] = event_date.isoformat()
    if start_time is not _UNSET:
        before["start_time"] = event.start_time
        event.start_time = start_time
        after["start_time"] = start_time
    if end_time is not _UNSET:
        before["end_time"] = event.end_time
        event.end_time = end_time
        after["end_time"] = end_time
    if required_count is not _UNSET:
        if required_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        before["required_count"] = event.required_count
        event.required_count = required_count
        after["required_count"] = required_count
    if reserve_count is not _UNSET:
        if reserve_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        before["reserve_count"] = event.reserve_count
        event.reserve_count = reserve_count
        after["reserve_count"] = reserve_count
    if location is not _UNSET:
        before["location"] = event.location
        event.location = location
        after["location"] = location
    if arrival_instructions is not _UNSET:
        before["arrival_instructions"] = event.arrival_instructions
        event.arrival_instructions = arrival_instructions
        after["arrival_instructions"] = arrival_instructions
    if contact_name is not _UNSET:
        before["contact_name"] = event.contact_name
        event.contact_name = contact_name
        after["contact_name"] = contact_name
    if contact_phone is not _UNSET:
        before["contact_phone"] = event.contact_phone
        event.contact_phone = contact_phone
        after["contact_phone"] = contact_phone
    if notes is not _UNSET:
        before["notes"] = event.notes
        event.notes = notes
        after["notes"] = notes
    write_audit(
        session, actor_id=actor_id, action="range_event.update", entity_type="range_event",
        entity_id=event.id, before=before, after=after,
    )
    session.commit()
    session.refresh(event)
    return event


def cancel_range_event(
    session: Session, *, event: RangeEvent, reason: str = "Cancelled", actor_id: uuid.UUID | None = None
) -> RangeEvent:
    reason = reason.strip()
    if not reason:
        raise RangeValidationError("reason_required")
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    previous_status = event.status
    event.cancellation_reason = reason
    event.status = RangeEventStatus.cancelled
    context = _range_context(event, reason=reason)
    assignments = session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == event.id
    )).scalars().all()
    for assignment in assignments:
        _range_notification(
            session, soldier_id=assignment.soldier_id, type=NotificationType.range_cancelled,
            title="Range cancelled", body=context, reference_type="range_event",
            reference_id=event.id, actor_id=actor_id,
        )
    if assignments and _mitvachim_enabled(session):
        notify_duty_managers_in_scope(session, soldier_id=assignments[0].soldier_id, type=NotificationType.range_cancelled, title="Range cancelled", body=context, reference_type="range_event", reference_id=event.id, actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="range_event.cancel", entity_type="range_event",
        entity_id=event.id, before={"status": previous_status}, after={"status": event.status},
    )
    session.commit()
    session.refresh(event)
    return event


def delete_range_event(session: Session, *, event: RangeEvent) -> None:
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    has_assignments = session.query(RangeAssignment.id).filter(
        RangeAssignment.range_event_id == event.id
    ).first()
    if has_assignments is not None:
        raise RangeValidationError("event_has_assignments")
    has_history = session.query(SoldierRangeQualification.id).filter(
        (SoldierRangeQualification.source_range_event_id == event.id)
        | SoldierRangeQualification.source_range_assignment_id.in_(
            select(RangeAssignment.id).where(RangeAssignment.range_event_id == event.id)
        )
    ).first()
    if has_history is not None:
        raise RangeValidationError("event_has_history")
    session.delete(event)
    session.commit()


def _validate_and_build_assignment(
    session: Session, *, event: RangeEvent, soldier_id: uuid.UUID, is_reserve: bool,
) -> RangeAssignment:
    """Same validation as add_range_assignment (subtree membership, exemption,
    same-date conflict) but only constructs the row — does not add/commit/notify.
    Shared by add_range_assignment (single, notifies) and assign_batch (many, one
    commit + one notification pass at the end)."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise RangeValidationError("soldier_not_found")
    node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    event_node = session.get(HierarchyNode, event.hierarchy_node_id)
    if node is None or event_node is None or event.hierarchy_node_id not in node.path_ids:
        raise RangeValidationError("soldier_outside_event_subunit")
    if is_range_exempt(session, soldier=soldier, event_date=event.date):
        raise RangeValidationError("soldier_range_exempt")
    existing_same_date = session.execute(
        select(RangeAssignment.id)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier_id,
            RangeEvent.date == event.date,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing_same_date is not None:
        raise RangeValidationError("soldier_already_assigned_on_date")
    return RangeAssignment(range_event_id=event.id, soldier_id=soldier_id, is_reserve=is_reserve)


def add_range_assignment(
    session: Session, *, event: RangeEvent, soldier_id: uuid.UUID, is_reserve: bool,
    assignment_reason_code: str = "manual", assignment_reason_text: str | None = "שיבוץ ידני",
) -> RangeAssignment:
    _acquire_range_assignment_date_lock(session, event_date=event.date)
    session.refresh(event)
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    assignment = _validate_and_build_assignment(session, event=event, soldier_id=soldier_id, is_reserve=is_reserve)

    existing_soldier_ids = set(session.execute(select(RangeAssignment.soldier_id).where(
        RangeAssignment.range_event_id == event.id,
    )).scalars())
    assignment.assignment_reason_code = assignment_reason_code
    assignment.assignment_reason_text = assignment_reason_text
    session.add(assignment)
    session.flush()
    _notify_roster_change(session, event=event, soldier_ids=existing_soldier_ids)
    _range_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.range_assignment_confirmed,
        title="שובצת למטווח",
        reference_type="range_assignment",
        reference_id=assignment.id,
    )
    session.commit()
    session.refresh(assignment)
    return assignment


def assign_batch(
    session: Session, *, event: RangeEvent,
    primary_soldier_ids: list[uuid.UUID], reserve_soldier_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> list[RangeAssignment]:
    """All-or-nothing: validates every soldier before adding any row, so a single
    invalid soldier in the batch fails the whole call with no partial writes.
    Deliberately simpler than shifts' assignBatch (which is partial-success/lenient) —
    the range candidate panel already is the review step, so failing fast on the
    first invalid soldier keeps this endpoint's contract simple."""
    _acquire_range_assignment_date_lock(session, event_date=event.date)
    session.refresh(event)
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")

    rows = [
        _validate_and_build_assignment(session, event=event, soldier_id=sid, is_reserve=False)
        for sid in primary_soldier_ids
    ] + [
        _validate_and_build_assignment(session, event=event, soldier_id=sid, is_reserve=True)
        for sid in reserve_soldier_ids
    ]
    for row in rows:
        session.add(row)
    session.flush()
    for row in rows:
        _range_notification(
            session, soldier_id=row.soldier_id, type=NotificationType.range_assignment_confirmed,
            title="שובצת למטווח", reference_type="range_assignment", reference_id=row.id,
        )
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def remove_range_assignment(session: Session, *, assignment: RangeAssignment, actor_id: uuid.UUID | None = None) -> None:
    event = session.get(RangeEvent, assignment.range_event_id)
    if event is not None and event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    remaining_ids = set(session.execute(select(RangeAssignment.soldier_id).where(
        RangeAssignment.range_event_id == assignment.range_event_id,
        RangeAssignment.id != assignment.id,
    )).scalars())
    soldier_id = assignment.soldier_id
    session.delete(assignment)
    session.flush()
    _notify_roster_change(
        session, event=event, soldier_ids=remaining_ids | {soldier_id}, actor_id=actor_id,
    )
    session.commit()


_VALIDITY_SETTING_KEYS: dict[str, str] = {
    RangeType.laser: "mitvachim.laser_validity_days",
    RangeType.live: "mitvachim.live_validity_days",
    RangeType.alal: "mitvachim.alal_validity_days",
}
_NO_SHOW_PENALTY = Decimal("-1")

# Fallback defaults if the corresponding setting row is missing, matching the
# defaults seeded by the add_ranges_tables migration.
_FALLBACK_VALIDITY_DAYS: dict[str, int] = {
    RangeType.laser: 180,
    RangeType.live: 365,
    RangeType.alal: 365,
}


def _validity_days(session: Session, range_type: str) -> int:
    key = _VALIDITY_SETTING_KEYS[range_type]
    try:
        value = get_setting(session, key)
    except SettingNotFound:
        return _FALLBACK_VALIDITY_DAYS[range_type]
    return int(value)


def _record_qualification(session: Session, *, soldier_id: uuid.UUID, range_type: str, valid_until: date,
                           source_range_assignment_id: uuid.UUID) -> None:
    session.add(SoldierRangeQualification(
        soldier_id=soldier_id, range_type=range_type, valid_until=valid_until,
        source_range_assignment_id=source_range_assignment_id,
        source_range_event_id=session.get(RangeAssignment, source_range_assignment_id).range_event_id,
    ))


def get_effective_range_qualification(session: Session, *, soldier_id: uuid.UUID, range_type: str) -> date | None:
    """Returns the soldier's current valid_until for range_type (the furthest-out
    valid_until among all non-deleted qualification rows for that soldier/type), or
    None if they have no qualification record at that type."""
    qualification = aliased(SoldierRangeQualification)
    assignment = aliased(RangeAssignment)
    return session.execute(
        select(func.max(qualification.valid_until))
        .outerjoin(assignment, qualification.source_range_assignment_id == assignment.id)
        .where(
            qualification.soldier_id == soldier_id,
            qualification.range_type == range_type,
            or_(qualification.source_range_assignment_id.is_(None), assignment.attendance_status == RangeAttendanceStatus.present),
        )
    ).scalar_one_or_none()


def _delete_qualification_from_this_assignment(session: Session, *, assignment: RangeAssignment) -> None:
    session.execute(delete(SoldierRangeQualification).where(
        SoldierRangeQualification.source_range_assignment_id == assignment.id,
    ))


def mark_attendance(
    session: Session, *, assignment: RangeAssignment, status: RangeAttendanceStatus,
    marked_by: uuid.UUID, note: str | None = None,
) -> RangeAssignment:
    if assignment.is_draft:
        raise RangeValidationError("assignment_not_confirmed")
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
    if previous_status == status:
        if status == RangeAttendanceStatus.no_show and _mitvachim_enabled(session):
            latest_body = f"{_range_context(event, reason=note)} | assignment={assignment.id}"
            session.query(Notification).filter(
                Notification.type == NotificationType.range_no_show,
                Notification.reference_type == "range_event",
                Notification.reference_id == event.id,
            ).update({Notification.body: latest_body}, synchronize_session=False)
        session.commit()
        session.refresh(assignment)
        return assignment
    no_show_transition = previous_status != RangeAttendanceStatus.no_show and status == RangeAttendanceStatus.no_show

    # Reverse the previous side effect, if any.
    if previous_status == RangeAttendanceStatus.no_show and assignment.score_adjustment_id is not None:
        original = session.get(ScoreAdjustment, assignment.score_adjustment_id)
        reversal_delta = -original.delta if original is not None else -_NO_SHOW_PENALTY
        create_adjustment(
            session, soldier_id=assignment.soldier_id, delta=reversal_delta,
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
        _range_notification(
            session, soldier_id=assignment.soldier_id, type=NotificationType.no_show_marked,
            title="נרשם היעדרות ממטווח", body=note, reference_type="range_assignment",
            reference_id=assignment.id, actor_id=marked_by,
        )
        if no_show_transition and _mitvachim_enabled(session):
            _range_notification(session, soldier_id=assignment.soldier_id, type=NotificationType.range_no_show, title="Range no-show recorded", body=f"{_range_context(event, reason=note)} | assignment={assignment.id}", reference_type="range_event", reference_id=event.id, actor_id=marked_by)
            notify_duty_managers_in_scope(
                session, soldier_id=assignment.soldier_id, type=NotificationType.range_no_show,
                title="Range no-show recorded",
                body=f"{_range_context(event, reason=note)} | assignment={assignment.id}",
                reference_type="range_event", reference_id=event.id, actor_id=marked_by,
            )

    assignment.attendance_status = status
    assignment.marked_by = marked_by
    assignment.marked_at = datetime.now(UTC)
    assignment.note = note

    write_audit(
        session, actor_id=marked_by, action="range_attendance_marked", entity_type="range_assignment",
        entity_id=assignment.id, before={"attendance_status": previous_status}, after={"attendance_status": status},
    )

    session.commit()
    session.refresh(assignment)
    return assignment
