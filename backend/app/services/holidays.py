from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import holidays as hol
from pydantic import BaseModel


class HolidayHit(BaseModel):
    date: date
    name: str


@lru_cache(maxsize=64)
def holidays_for_year(year: int) -> dict[date, str]:
    """IL holiday calendar for one Gregorian year, cached (the `holidays`
    package rebuilds its internal table on every call otherwise, which is
    wasteful when many shifts/constraints in the same request need it)."""
    return dict(hol.country_holidays("IL", years=year))


def holidays_in_range(start: date, end: date, *, end_inclusive: bool) -> list[HolidayHit]:
    """Holidays touching [start, last_day], where last_day is `end` itself
    when end_inclusive, or the day before `end` otherwise (DutyShift/
    CalendarShiftOut end_date is exclusive — the first day NOT covered)."""
    last_day = end if end_inclusive else end - timedelta(days=1)
    if last_day < start:
        return []
    merged: dict[date, str] = {}
    for year in range(start.year, last_day.year + 1):
        merged.update(holidays_for_year(year))
    return [
        HolidayHit(date=d, name=name)
        for d, name in sorted(merged.items())
        if start <= d <= last_day
    ]
