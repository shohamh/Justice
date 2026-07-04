from __future__ import annotations

from datetime import date, datetime

from app.algorithm.rest import last_duty_day, rest_violated


def test_last_duty_day_multi_day_exclusive_end():
    # A duty spanning [2026-06-01, 2026-06-04) touches 06-01, 06-02, 06-03.
    assert last_duty_day(date(2026, 6, 1), date(2026, 6, 4)) == date(2026, 6, 3)


def test_last_duty_day_single_day_sentinel():
    # start_date == end_date is used as a single-day sentinel by some callers.
    assert last_duty_day(date(2026, 6, 1), date(2026, 6, 1)) == date(2026, 6, 1)


def test_rest_satisfied_8am_to_5pm_then_8am_next_day():
    """Explicit scenario from the design spec: a duty ending at 17:00, followed
    by another starting at 08:00 the next day, is a 15h gap — satisfies a 12h
    rest requirement with no extra blocked days."""
    prior_end_dt = datetime(2026, 6, 1, 17, 0)
    assert rest_violated(prior_end_dt, date(2026, 6, 2), "08:00", rest_hours=12) is False


def test_rest_violated_same_day_start():
    prior_end_dt = datetime(2026, 6, 1, 17, 0)
    assert rest_violated(prior_end_dt, date(2026, 6, 1), "18:00", rest_hours=12) is True


def test_rest_violated_next_day_too_early():
    """5pm to 6am next day is only a 13h gap... but 5pm to 5:30am is 12.5h — still
    fine. Push it under 12h: 5pm to 4am next day is 11h — violated."""
    prior_end_dt = datetime(2026, 6, 1, 17, 0)
    assert rest_violated(prior_end_dt, date(2026, 6, 2), "04:00", rest_hours=12) is True


def test_rest_hours_zero_never_violated():
    prior_end_dt = datetime(2026, 6, 1, 17, 0)
    assert rest_violated(prior_end_dt, date(2026, 6, 1), "17:01", rest_hours=0) is False
