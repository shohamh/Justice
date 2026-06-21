from datetime import date

from app.algorithm.duration import calendar_days_touched, score_days


def test_calendar_days_touched_single_day():
    assert calendar_days_touched(date(2026, 6, 1), date(2026, 6, 2)) == 1


def test_calendar_days_touched_multi_day():
    assert calendar_days_touched(date(2026, 6, 1), date(2026, 6, 8)) == 7


def test_score_days_same_day_partial_hours():
    # 8am-5pm, touches 1 calendar day -> 9 hours -> ceil to 1 day.
    assert score_days(date(2026, 6, 1), date(2026, 6, 2), "08:00", "17:00") == 1


def test_score_days_exact_week_spanning_eight_calendar_days():
    # Monday 14:00 -> following Monday 14:00: duration_days=8 (touches 8 calendar
    # dates), but exactly 168 hours = 7*24h elapsed -> scores as 7 days.
    assert score_days(date(2026, 6, 1), date(2026, 6, 9), "14:00", "14:00") == 7

    # calendar_days_touched is still 8 -- the window-relevant count is unaffected.
    assert calendar_days_touched(date(2026, 6, 1), date(2026, 6, 9)) == 8


def test_score_days_default_full_day_reproduces_calendar_days_touched():
    # The "00:00"/"23:59" defaults used everywhere a real time isn't known should
    # reproduce today's exact whole-day count for any duration.
    for n in (1, 2, 5, 14):
        end = date(2026, 6, 1).fromordinal(date(2026, 6, 1).toordinal() + n)
        assert score_days(date(2026, 6, 1), end, "00:00", "23:59") == n


def test_score_days_overnight_two_calendar_days_one_score_day():
    # 23:00 -> 01:00 next day: touches 2 calendar dates, 2 hours elapsed -> 1 day.
    assert score_days(date(2026, 6, 1), date(2026, 6, 3), "23:00", "01:00") == 1
