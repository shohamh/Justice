from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyShift, ShiftTemplate


class TemplateError(Exception):
    """Raised on invalid template operations."""


_VALID_WEEKDAYS = {1, 2, 3, 4, 5, 6, 7}
_VALID_RECURRENCE = {"daily", "weekdays", "weekly"}
# Israeli work week: Sun(7), Mon(1), Tue(2), Wed(3), Thu(4)
_ISRAELI_WORKWEEK = [7, 1, 2, 3, 4]


# SYNC: mirrored in frontend/src/components/ShiftTemplateFormModal.tsx (countAutoRollInstances).
def _effective_weekdays(recurrence_type: str, weekdays: list[int]) -> set[int]:
    if recurrence_type == "daily":
        return _VALID_WEEKDAYS
    if recurrence_type == "weekdays":
        return set(_ISRAELI_WORKWEEK)
    return set(weekdays)


def expand_dates(
    *, recurrence_type: str = "weekly", weekdays: list[int], range_start: date, range_end: date
) -> list[date]:
    """Return every date in [range_start, range_end] matching the recurrence rule.

    recurrence_type:
      "daily"    – every calendar day
      "weekdays" – Israeli work week (Sun–Thu)
      "weekly"   – specific ISO weekdays in `weekdays` (Mon=1 … Sun=7)
    """
    selected = _effective_weekdays(recurrence_type, weekdays)
    out: list[date] = []
    if not selected or range_end < range_start:
        return out
    day = range_start
    while day <= range_end:
        if day.isoweekday() in selected:
            out.append(day)
        day += timedelta(days=1)
    return out


def _validate(
    recurrence_type: str,
    weekdays: list[int],
    duration_days: int,
    required_count: int,
    start_time: str,
    end_time: str,
    auto_roll_until: date | None = None,
) -> None:
    if recurrence_type not in _VALID_RECURRENCE:
        raise TemplateError("invalid_recurrence_type")
    if recurrence_type == "weekly" and (not weekdays or not set(weekdays) <= _VALID_WEEKDAYS):
        raise TemplateError("invalid_weekdays")
    if not (1 <= duration_days <= 14):
        raise TemplateError("invalid_duration_days")
    if required_count < 1:
        raise TemplateError("invalid_required_count")
    for t in (start_time, end_time):
        parts = t.split(":")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise TemplateError("invalid_time")
    if auto_roll_until is not None and auto_roll_until < date.today():
        raise TemplateError("invalid_auto_roll_until")


def create_template(
    session: Session,
    *,
    name: str,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    recurrence_type: str = "weekly",
    weekdays: list[int],
    duration_days: int = 1,
    start_time: str = "00:00",
    end_time: str = "23:59",
    required_count: int = 1,
    auto_roll: bool = False,
    auto_roll_until: date | None = None,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    _validate(recurrence_type, weekdays, duration_days, required_count, start_time, end_time, auto_roll_until)
    tpl = ShiftTemplate(
        name=name,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        recurrence_type=recurrence_type,
        weekdays=sorted(set(weekdays)) if recurrence_type == "weekly" else [],
        duration_days=duration_days,
        start_time=start_time,
        end_time=end_time,
        required_count=required_count,
        auto_roll=auto_roll,
        auto_roll_until=auto_roll_until,
        notes=notes,
        created_by=actor_id,
    )
    session.add(tpl)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.create",
        entity_type="shift_template",
        entity_id=tpl.id,
        after={"name": name, "recurrence_type": recurrence_type, "weekdays": tpl.weekdays, "duration_days": duration_days, "auto_roll": auto_roll, "auto_roll_until": auto_roll_until.isoformat() if auto_roll_until else None},
    )
    return tpl


def list_templates(session: Session, *, include_inactive: bool = False) -> list[ShiftTemplate]:
    q = select(ShiftTemplate)
    if not include_inactive:
        q = q.where(ShiftTemplate.active.is_(True))
    return list(session.execute(q.order_by(ShiftTemplate.name)).scalars().all())


def update_template(
    session: Session,
    *,
    tpl: ShiftTemplate,
    name: str | None = None,
    recurrence_type: str | None = None,
    weekdays: list[int] | None = None,
    duration_days: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    required_count: int | None = None,
    auto_roll: bool | None = None,
    auto_roll_until: object = ...,
    active: bool | None = None,
    notes: object = ...,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    before = {"name": tpl.name, "recurrence_type": tpl.recurrence_type, "weekdays": tpl.weekdays, "duration_days": tpl.duration_days, "active": tpl.active, "auto_roll": tpl.auto_roll}
    if name is not None:
        tpl.name = name
    if recurrence_type is not None:
        tpl.recurrence_type = recurrence_type
    if weekdays is not None:
        tpl.weekdays = sorted(set(weekdays))
    if duration_days is not None:
        tpl.duration_days = duration_days
    if start_time is not None:
        tpl.start_time = start_time
    if end_time is not None:
        tpl.end_time = end_time
    if required_count is not None:
        tpl.required_count = required_count
    if auto_roll is not None:
        tpl.auto_roll = auto_roll
    if auto_roll_until is not ...:
        tpl.auto_roll_until = auto_roll_until  # type: ignore[assignment]
    if active is not None:
        tpl.active = active
    if notes is not ...:
        tpl.notes = notes  # type: ignore[assignment]
    if tpl.recurrence_type != "weekly":
        tpl.weekdays = []
        tpl.duration_days = 1
    _validate(tpl.recurrence_type, tpl.weekdays, tpl.duration_days, tpl.required_count, tpl.start_time, tpl.end_time, tpl.auto_roll_until)
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.update",
        entity_type="shift_template",
        entity_id=tpl.id,
        before=before,
        after={"name": tpl.name, "recurrence_type": tpl.recurrence_type, "weekdays": tpl.weekdays, "active": tpl.active, "auto_roll": tpl.auto_roll},
    )
    return tpl


def delete_template(session: Session, *, tpl: ShiftTemplate, actor_id: uuid.UUID | None = None) -> None:
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.delete",
        entity_type="shift_template",
        entity_id=tpl.id,
        before={"name": tpl.name},
    )
    session.delete(tpl)


def _existing_dates(
    session: Session, *, template_id: uuid.UUID, dates: list[date]
) -> set[date]:
    """Start dates in `dates` that already have a shift generated from this template."""
    if not dates:
        return set()
    rows = session.execute(
        select(DutyShift.start_date).where(
            DutyShift.generated_from_template_id == template_id,
            DutyShift.start_date.in_(dates),
        )
    ).scalars().all()
    return set(rows)


def preview_generation(
    session: Session, *, tpl: ShiftTemplate, range_start: date, range_end: date
) -> list[dict]:
    """Return [{date, exists}] for each recurring date in the range. No mutation."""
    dates = expand_dates(recurrence_type=tpl.recurrence_type, weekdays=tpl.weekdays, range_start=range_start, range_end=range_end)
    existing = _existing_dates(session, template_id=tpl.id, dates=dates)
    return [{"date": d, "exists": d in existing} for d in dates]


def generate_shifts(
    session: Session,
    *,
    tpl: ShiftTemplate,
    range_start: date,
    range_end: date,
    actor_id: uuid.UUID | None = None,
) -> list[DutyShift]:
    """Idempotently create one single-day DutyShift per recurring date that does not
    already have one from this template. Returns the newly created shifts."""
    dates = expand_dates(recurrence_type=tpl.recurrence_type, weekdays=tpl.weekdays, range_start=range_start, range_end=range_end)
    existing = _existing_dates(session, template_id=tpl.id, dates=dates)
    created: list[DutyShift] = []
    for d in dates:
        if d in existing:
            continue
        shift = DutyShift(
            duty_type_id=tpl.duty_type_id,
            duty_location_id=tpl.duty_location_id,
            start_date=d,
            end_date=d + timedelta(days=tpl.duration_days),
            required_count=tpl.required_count,
            notes=tpl.notes,
            created_by=actor_id,
            generated_from_template_id=tpl.id,
        )
        session.add(shift)
        created.append(shift)
    session.flush()
    if created:
        write_audit(
            session,
            actor_id=actor_id,
            action="shift_template.generate",
            entity_type="shift_template",
            entity_id=tpl.id,
            after={"created_count": len(created), "range_start": range_start.isoformat(), "range_end": range_end.isoformat()},
        )
    return created


def roll_horizon(
    session: Session,
    *,
    horizon_days: int = 30,
    today: date | None = None,
    actor_id: uuid.UUID | None = None,
) -> int:
    """Materialise the next `horizon_days` days of shifts for every active auto_roll
    template. Idempotent (relies on generate_shifts). Returns total shifts created.

    Templates with `auto_roll_until` set have their generation window clamped to that
    date; templates whose `auto_roll_until` has already passed are skipped entirely.
    """
    base = today or date.today()
    range_end = base + timedelta(days=horizon_days - 1)
    templates = session.execute(
        select(ShiftTemplate).where(
            ShiftTemplate.active.is_(True), ShiftTemplate.auto_roll.is_(True)
        )
    ).scalars().all()
    total = 0
    for tpl in templates:
        if tpl.auto_roll_until is not None and tpl.auto_roll_until < base:
            continue
        tpl_range_end = range_end
        if tpl.auto_roll_until is not None and tpl.auto_roll_until < tpl_range_end:
            tpl_range_end = tpl.auto_roll_until
        created = generate_shifts(
            session, tpl=tpl, range_start=base, range_end=tpl_range_end, actor_id=actor_id
        )
        total += len(created)
    return total
