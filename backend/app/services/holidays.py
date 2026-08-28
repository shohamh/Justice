from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import holidays as hol
from pydantic import BaseModel


class HolidayHit(BaseModel):
    date: date
    name: str


# These are the Israeli holidays represented by the app that have a distinct
# ערב חג. The list is deliberately explicit: not every holiday has one.
_HOLIDAYS_WITH_EVE = frozenset(
    {
        "ראש השנה",
        "יום כיפור",
        "סוכות",
        "שמחת תורה/שמיני עצרת",
        "פסח",
        "שביעי של פסח",
        "שבועות",
    }
)


@lru_cache(maxsize=64)
def holidays_for_year(year: int) -> dict[date, str]:
    """IL holiday calendar for one Gregorian year, cached (the `holidays`
    package rebuilds its internal table on every call otherwise, which is
    wasteful when many shifts/constraints in the same request need it)."""
    return dict(hol.country_holidays("IL", years=year))


def calendar_holidays_for_year(year: int) -> dict[date, str]:
    """Return the app's holidays plus the explicitly approved ערב חג dates."""
    holidays = holidays_for_year(year)
    result = dict(holidays)
    for holiday_date, name in holidays.items():
        if name not in _HOLIDAYS_WITH_EVE:
            continue
        eve = holiday_date - timedelta(days=1)
        if eve.year == year and eve not in holidays:
            result[eve] = f"ערב {name}"
    return result


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
