from __future__ import annotations

import math
from datetime import date, datetime


def combine_date_time(d: date, hhmm: str) -> datetime:
    """Combine a calendar date with an "HH:MM" wall-clock time into a datetime."""
    h, m = hhmm.split(":")
    return datetime(d.year, d.month, d.day, int(h), int(m))


def calendar_days_touched(start_date: date, end_date: date) -> int:
    """Number of distinct calendar dates in [start_date, end_date) — end_date is
    exclusive (the first day NOT touched). This is what rolling-window/rest
    constraints care about: which calendar dates a duty occupies."""
    return (end_date - start_date).days


def _parse_hhmm(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def score_days(start_date: date, end_date: date, start_time: str, end_time: str) -> int:
    """Wall-clock duration of the duty, rounded up to whole days, for effort-score
    purposes. `start_time` is the clock time on `start_date`; `end_time` is the
    clock time on `end_date - 1 day` (the LAST calendar day touched, not end_date
    itself, which is never touched)."""
    days_touched = calendar_days_touched(start_date, end_date)
    elapsed_minutes = (days_touched - 1) * 24 * 60 + (_parse_hhmm(end_time) - _parse_hhmm(start_time))
    return max(1, math.ceil(elapsed_minutes / (24 * 60)))
