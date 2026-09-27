"""Project persisted Justice schedules into attendee-visible calendar snapshots.

This module does no Exchange I/O. The worker converts its Israel-aware datetimes
to EWS datetimes only when sending a meeting request.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    HierarchyNode,
    RangeAssignment,
    RangeEvent,
    RangeLocation,
    Soldier,
)

ISRAEL = ZoneInfo("Asia/Jerusalem")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SourceType(StrEnum):
    DUTY_SHIFT = "duty_shift"
    DUTY_ASSIGNMENT = "duty_assignment"
    RANGE_EVENT = "range_event"


class ProjectionError(ValueError):
    """An official source has data that cannot safely be put on a calendar."""

    def __init__(self, code: str, safe_message: str):
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


@dataclass(frozen=True)
class ProjectedAttendee:
    email: str
    display_name: str
    required: bool


@dataclass(frozen=True)
class ProjectionProblem:
    code: str
    safe_message: str


@dataclass(frozen=True)
class CalendarSnapshot:
    source_key: str
    source_type: SourceType
    source_id: UUID
    subject: str
    start: datetime
    end: datetime
    all_day: bool
    location: str
    body: str
    attendees: tuple[ProjectedAttendee, ...]
    problems: tuple[ProjectionProblem, ...]
    content_hash: str


def israel_local_datetime(day: date, clock: str | time) -> datetime:
    """Choose the first occurrence in a repeated hour; reject a skipped hour."""
    try:
        parsed = time.fromisoformat(clock) if isinstance(clock, str) else clock
        if parsed is None or parsed.tzinfo is not None:
            raise ValueError("missing or timezone-aware time")
        local = datetime.combine(day, parsed).replace(tzinfo=ISRAEL, fold=0)
        if local.astimezone(UTC).astimezone(ISRAEL).replace(tzinfo=None) != local.replace(tzinfo=None):
            raise ValueError("nonexistent local time")
    except (TypeError, ValueError) as exc:
        raise ProjectionError("invalid_local_time", "The schedule contains an invalid Israel local time.") from exc
    return local


def _add_months(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    for candidate in range(day.day, 27, -1):
        try:
            return date(year, month, candidate)
        except ValueError:
            pass
    return date(year, month, min(day.day, 28))


def _eligible(start: date, end: date, today: date) -> bool:
    return end >= today and start <= _add_months(today, 12)


def _email(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    return normalized if _EMAIL.fullmatch(normalized) else None


def _name(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _status(value: object) -> str:
    return str(getattr(value, "value", value))


class _Attendees:
    def __init__(self, session: Session):
        self.session = session
        self.by_email: dict[str, ProjectedAttendee] = {}
        self.problems: list[ProjectionProblem] = []

    def add(self, person: Soldier | None, *, required: bool) -> None:
        if person is None:
            self.problems.append(ProjectionProblem("missing_person", "An assigned person could not be found."))
            return
        email = _email(person.email)
        if email is None:
            self.problems.append(ProjectionProblem("missing_email", "An invited person has no usable email address."))
            return
        previous = self.by_email.get(email)
        self.by_email[email] = ProjectedAttendee(
            email, person.full_name, required or (previous.required if previous else False),
        )

    def commander_for(self, person: Soldier | None) -> None:
        if person is None or person.hierarchy_node_id is None:
            return
        node = self.session.get(HierarchyNode, person.hierarchy_node_id)
        if node is not None and node.commander_id is not None and node.commander_id != person.id:
            self.add(self.session.get(Soldier, node.commander_id), required=False)

    def finish(self) -> tuple[ProjectedAttendee, ...]:
        return tuple(self.by_email[key] for key in sorted(self.by_email))


def _contact(session: Session, attendees: _Attendees, name: str | None, phone: str | None, body: list[str]) -> None:
    if not name:
        return
    matches = [person for person in session.scalars(select(Soldier)).all() if _name(person.full_name) == _name(name) and _email(person.email)]
    if len(matches) == 1:
        attendees.add(matches[0], required=False)
    else:
        body.append(f"Contact: {name.strip()}")
        if phone:
            body.append(f"Contact phone: {phone.strip()}")


def _snapshot(
    source_type: SourceType, source_id: UUID, subject: str, start: datetime,
    end: datetime, all_day: bool, location: str, body: list[str], attendees: _Attendees,
) -> CalendarSnapshot:
    if end <= start:
        raise ProjectionError("invalid_interval", "The schedule ends before it starts.")
    invitation = attendees.finish()
    visible_body = "\n".join(part.strip() for part in body if part and part.strip())
    payload = {
        "subject": subject, "start": start.isoformat(), "end": end.isoformat(),
        "all_day": all_day, "location": location, "body": visible_body,
        "attendees": [(item.email, item.display_name, item.required) for item in invitation],
    }
    digest = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return CalendarSnapshot(
        f"{source_type.value}:{source_id}", source_type, source_id, subject,
        start, end, all_day, location, visible_body, invitation,
        tuple(attendees.problems), digest,
    )


def _duty(session: Session, source_type: SourceType, source: DutyShift | DutyAssignment, today: date) -> CalendarSnapshot | None:
    if _status(source.status) in {"cancelled", "deleted"}:
        return None
    if not _eligible(source.start_date, source.end_date, today):
        return None
    duty_type = session.get(DutyType, source.duty_type_id)
    location = session.get(DutyLocation, source.duty_location_id)
    if duty_type is None or location is None:
        raise ProjectionError("missing_source_label", "The schedule has a missing duty type or location.")
    attendees = _Attendees(session)
    body: list[str] = []
    if duty_type.instructions:
        body.append(duty_type.instructions)
    # Standalone assignment notes belong to a soldier, not to a shared event.
    if source.notes and source_type is SourceType.DUTY_SHIFT:
        body.append(source.notes)
    if source_type is SourceType.DUTY_SHIFT:
        assignments = [a for a in session.scalars(select(DutyAssignment).where(DutyAssignment.duty_shift_id == source.id)).all() if a.duty_shift_id == source.id and _status(a.status) == "published"]
    else:
        assignments = [source]
    for assignment in assignments:
        person = session.get(Soldier, assignment.soldier_id)
        called_up = bool(
            assignment.is_reserve and assignment.called_up_from and assignment.called_up_to
            and assignment.called_up_from <= source.end_date and assignment.called_up_to >= source.start_date
        )
        attendees.add(person, required=not assignment.is_reserve or called_up)
        attendees.commander_for(person)
        if called_up:
            body.append(f"Reserve call-up: {person.full_name if person else 'assigned soldier'}: {assignment.called_up_from.isoformat()} - {assignment.called_up_to.isoformat()}")
    _contact(session, attendees, duty_type.contact_name, duty_type.contact_phone, body)
    start = israel_local_datetime(source.start_date, source.start_time)
    end = israel_local_datetime(source.end_date, source.end_time)
    return _snapshot(source_type, source.id, f"{duty_type.name} - {location.name}", start, end, False, location.name, body, attendees)


def _range(session: Session, event: RangeEvent, today: date) -> CalendarSnapshot | None:
    if _status(event.status) == "cancelled" or not _eligible(event.date, event.date, today):
        return None
    location = session.get(RangeLocation, event.range_location_id)
    if location is None:
        raise ProjectionError("missing_source_label", "The range has a missing location.")
    if (event.start_time is None) != (event.end_time is None):
        raise ProjectionError("incomplete_range_time", "The range has only one of its two times.")
    all_day = event.start_time is None
    if all_day:
        start = israel_local_datetime(event.date, time.min)
        end = israel_local_datetime(event.date + timedelta(days=1), time.min)
    else:
        start = israel_local_datetime(event.date, event.start_time)
        end = israel_local_datetime(event.date, event.end_time)
    attendees = _Attendees(session)
    assignments = [a for a in session.scalars(select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)).all() if a.range_event_id == event.id and not a.is_draft]
    for assignment in assignments:
        person = session.get(Soldier, assignment.soldier_id)
        attendees.add(person, required=not assignment.is_reserve)
        attendees.commander_for(person)
    if event.responsible_duty_manager_id:
        attendees.add(session.get(Soldier, event.responsible_duty_manager_id), required=False)
    body = [event.arrival_instructions or "", event.notes or ""]
    _contact(session, attendees, event.contact_name, event.contact_phone, body)
    range_type = _status(event.range_type)
    return _snapshot(SourceType.RANGE_EVENT, event.id, f"{range_type} - {location.name}", start, end, all_day, location.name, body, attendees)


def project_source(session: Session, source_type: SourceType | str, source_id: UUID, *, today: date) -> CalendarSnapshot | None:
    """Return the current official event within the creation window, if any."""
    try:
        kind = SourceType(source_type)
    except ValueError as exc:
        raise ProjectionError("unknown_source", "The calendar source type is unsupported.") from exc
    model = {SourceType.DUTY_SHIFT: DutyShift, SourceType.DUTY_ASSIGNMENT: DutyAssignment, SourceType.RANGE_EVENT: RangeEvent}[kind]
    source = session.get(model, source_id)
    if source is None:
        return None
    if kind is SourceType.DUTY_ASSIGNMENT and source.duty_shift_id is not None:
        return None
    if kind is SourceType.RANGE_EVENT:
        return _range(session, source, today)
    return _duty(session, kind, source, today)
