from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyManagerScope,
    HierarchyNode,
    NotificationType,
    RangeAssignment,
    RangeEvent,
    RangeEventStatus,
    RangeLocation,
    SystemSetting,
)
from app.services.notifications import create_notification

_DEFAULT_DAYS = 3


def _int_setting(session: Session, key: str, default: int) -> int:
    row = session.get(SystemSetting, key)
    try:
        return int(row.value) if row is not None else default
    except (TypeError, ValueError):
        return default


def _event_details(session: Session, event: RangeEvent) -> str:
    location = session.get(RangeLocation, event.range_location_id)
    location_name = location.name if location else ""
    parts = [f"תאריך: {event.date.isoformat()}", f"מיקום: {location_name}"]
    if event.start_time:
        parts.append(f"שעה: {event.start_time}")
    if event.contact_name:
        parts.append(f"איש קשר: {event.contact_name}")
    if event.contact_phone:
        parts.append(f"טלפון: {event.contact_phone}")
    return " | ".join(parts)


def _manager_ids(session: Session, event: RangeEvent) -> set:
    node = session.get(HierarchyNode, event.hierarchy_node_id)
    if node is None or not node.path_ids:
        return set()
    return set(session.execute(
        select(DutyManagerScope.duty_manager_id).where(DutyManagerScope.hierarchy_node_id.in_(node.path_ids))
    ).scalars())


def send_due_range_reminders(session: Session, *, today: date | None = None) -> int:
    enabled = session.get(SystemSetting, "mitvachim.enabled")
    if enabled is None or enabled.value is not True:
        return 0
    today = today or date.today()
    threshold = _int_setting(session, "mitvachim.reminder_days_before", _DEFAULT_DAYS)
    events = session.execute(select(RangeEvent).where(
        RangeEvent.status == RangeEventStatus.planned,
        RangeEvent.reminder_sent_at.is_(None),
    )).scalars().all()
    sent = 0
    for event in events:
        if (event.date - today).days != threshold:
            continue
        assignments = session.execute(select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)).scalars().all()
        primary = sum(1 for a in assignments if not a.is_reserve and not a.is_draft)
        reserve = sum(1 for a in assignments if a.is_reserve and not a.is_draft)
        shortfall = primary < event.required_count or reserve < event.reserve_count
        details = _event_details(session, event)
        for assignment in assignments:
            if assignment.is_draft:
                continue
            create_notification(session, soldier_id=assignment.soldier_id, type=NotificationType.range_reminder,
                                title="תזכורת למטווח קרוב", body=details,
                                reference_type="range_event", reference_id=event.id)
        manager_type = NotificationType.range_reminder_shortfall if shortfall else NotificationType.range_reminder
        fill = f"שיבוץ ראשי: {primary}/{event.required_count}, רזרבה: {reserve}/{event.reserve_count}"
        body = f"{details} | {fill}"
        if shortfall:
            body += " | נדרש להשלים את השיבוץ לפני המטווח"
        for manager_id in _manager_ids(session, event):
            create_notification(session, soldier_id=manager_id, type=manager_type,
                                title="אזהרת מחסור בשיבוץ למטווח" if shortfall else "תזכורת למטווח קרוב",
                                body=body, reference_type="range_event", reference_id=event.id)
        event.reminder_sent_at = datetime.now(UTC)
        sent += 1
    if sent:
        session.commit()
    return sent
