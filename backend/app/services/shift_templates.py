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
