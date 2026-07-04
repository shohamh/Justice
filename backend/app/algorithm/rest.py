from __future__ import annotations

from datetime import date, datetime, timedelta

from app.algorithm.duration import combine_date_time


def last_duty_day(start_date: date, end_date: date) -> date:
    """The last calendar day actually touched by a duty. `end_date` is
    exclusive for multi-day duties (see duration.calendar_days_touched); for
    single-day sentinel duties where start_date == end_date (used by some
    test/call sites), the day itself is the last day."""
    return end_date - timedelta(days=1) if end_date > start_date else end_date


def rest_violated(
    prior_end_dt: datetime,
    next_start_date: date,
    next_start_time: str,
    rest_hours: int,
) -> bool:
    """True if starting a duty at (next_start_date, next_start_time) does not
    leave `rest_hours` of rest after `prior_end_dt`. rest_hours <= 0 means no
    rest requirement (never violated)."""
    if rest_hours <= 0:
        return False
    next_start_dt = combine_date_time(next_start_date, next_start_time)
    return next_start_dt < prior_end_dt + timedelta(hours=rest_hours)
