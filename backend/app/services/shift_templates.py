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


def expand_dates(*, weekdays: list[int], range_start: date, range_end: date) -> list[date]:
    """Return every date in [range_start, range_end] whose ISO weekday is in `weekdays`.

    ISO weekday: Mon=1 … Sun=7. Order preserved (ascending by date).
    """
    selected = set(weekdays)
    out: list[date] = []
    if not selected or range_end < range_start:
        return out
    day = range_start
    while day <= range_end:
        if day.isoweekday() in selected:
            out.append(day)
        day += timedelta(days=1)
    return out


_VALID_WEEKDAYS = {1, 2, 3, 4, 5, 6, 7}


def _validate(weekdays: list[int], required_count: int, start_time: str, end_time: str) -> None:
    if not weekdays or not set(weekdays) <= _VALID_WEEKDAYS:
        raise TemplateError("invalid_weekdays")
    if required_count < 1:
        raise TemplateError("invalid_required_count")
    for t in (start_time, end_time):
        parts = t.split(":")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise TemplateError("invalid_time")


def create_template(
    session: Session,
    *,
    name: str,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    weekdays: list[int],
    start_time: str = "00:00",
    end_time: str = "23:59",
    required_count: int = 1,
    auto_roll: bool = False,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    _validate(weekdays, required_count, start_time, end_time)
    tpl = ShiftTemplate(
        name=name,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        weekdays=sorted(set(weekdays)),
        start_time=start_time,
        end_time=end_time,
        required_count=required_count,
        auto_roll=auto_roll,
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
        after={"name": name, "weekdays": tpl.weekdays, "auto_roll": auto_roll},
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
    weekdays: list[int] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    required_count: int | None = None,
    auto_roll: bool | None = None,
    active: bool | None = None,
    notes: object = ...,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    before = {"name": tpl.name, "weekdays": tpl.weekdays, "active": tpl.active, "auto_roll": tpl.auto_roll}
    if name is not None:
        tpl.name = name
    if weekdays is not None:
        tpl.weekdays = sorted(set(weekdays))
    if start_time is not None:
        tpl.start_time = start_time
    if end_time is not None:
        tpl.end_time = end_time
    if required_count is not None:
        tpl.required_count = required_count
    if auto_roll is not None:
        tpl.auto_roll = auto_roll
    if active is not None:
        tpl.active = active
    if notes is not ...:
        tpl.notes = notes  # type: ignore[assignment]
    _validate(tpl.weekdays, tpl.required_count, tpl.start_time, tpl.end_time)
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.update",
        entity_type="shift_template",
        entity_id=tpl.id,
        before=before,
        after={"name": tpl.name, "weekdays": tpl.weekdays, "active": tpl.active, "auto_roll": tpl.auto_roll},
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
