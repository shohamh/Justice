from datetime import date

from app.services.shift_templates import expand_dates


def test_expand_dates_weekly_filters_to_selected_weekdays():
    # 2026-06-01 is a Monday. Select Mon(1), Wed(3), Fri(5).
    out = expand_dates(
        weekdays=[1, 3, 5],
        range_start=date(2026, 6, 1),
        range_end=date(2026, 6, 7),
    )
    assert out == [date(2026, 6, 1), date(2026, 6, 3), date(2026, 6, 5)]


def test_expand_dates_empty_weekdays_returns_nothing():
    out = expand_dates(weekdays=[], range_start=date(2026, 6, 1), range_end=date(2026, 6, 7))
    assert out == []


def test_expand_dates_inclusive_bounds():
    # Sunday is ISO 7. 2026-06-07 is a Sunday.
    out = expand_dates(weekdays=[7], range_start=date(2026, 6, 1), range_end=date(2026, 6, 7))
    assert out == [date(2026, 6, 7)]
