from __future__ import annotations

from datetime import date

from app.services.holidays import HolidayHit, calendar_holidays_for_year, holidays_in_range


def test_inclusive_range_includes_holiday_on_end_date():
    # Rosh Hashana 5787 starts the evening of 2026-09-11; the `holidays`
    # package marks 2026-09-12 as "ראש השנה".
    hits = holidays_in_range(date(2026, 9, 12), date(2026, 9, 12), end_inclusive=True)
    assert hits == [HolidayHit(date=date(2026, 9, 12), name="ראש השנה")]


def test_exclusive_range_excludes_holiday_on_end_date():
    # Same date, but as an exclusive shift end_date the holiday on that date
    # is NOT covered (the shift's last worked day is the day before).
    hits = holidays_in_range(date(2026, 9, 11), date(2026, 9, 12), end_inclusive=False)
    assert hits == []


def test_exclusive_range_includes_holiday_the_day_before_end_date():
    hits = holidays_in_range(date(2026, 9, 12), date(2026, 9, 13), end_inclusive=False)
    assert hits == [HolidayHit(date=date(2026, 9, 12), name="ראש השנה")]


def test_range_spanning_year_boundary():
    # Test that a range spanning two calendar years correctly includes holidays
    # from both years. Uses Rosh Hashanah which occurs in both 2025 and 2026.
    hits = holidays_in_range(date(2025, 9, 22), date(2026, 9, 13), end_inclusive=True)
    # Should include Rosh Hashanah from both years
    dates_found = [hit.date for hit in hits]
    assert date(2025, 9, 23) in dates_found  # 2025 Rosh Hashanah (day 1)
    assert date(2026, 9, 12) in dates_found  # 2026 Rosh Hashanah (day 1)


def test_range_with_no_holidays_returns_empty_list():
    hits = holidays_in_range(date(2026, 6, 1), date(2026, 6, 5), end_inclusive=True)
    assert hits == []


def test_end_before_start_after_exclusive_adjustment_returns_empty_list():
    # A same-day exclusive-end shift (start_date == end_date) covers zero
    # days — must not raise or invert the range.
    hits = holidays_in_range(date(2026, 6, 1), date(2026, 6, 1), end_inclusive=False)
    assert hits == []


def test_calendar_holidays_include_the_explicit_eve_holiday_list():
    holidays = calendar_holidays_for_year(2026)

    assert holidays[date(2026, 9, 11)] == "ערב ראש השנה"
    assert holidays[date(2026, 9, 20)] == "ערב יום כיפור"
    assert holidays[date(2026, 9, 25)] == "ערב סוכות"
    assert holidays[date(2026, 10, 2)] == "ערב שמחת תורה/שמיני עצרת"
    assert holidays[date(2026, 4, 1)] == "ערב פסח"
    assert holidays[date(2026, 4, 7)] == "ערב שביעי של פסח"
    assert holidays[date(2026, 5, 21)] == "ערב שבועות"

    assert date(2026, 4, 21) not in holidays  # יום העצמאות has no ערב חג.
    assert date(2026, 3, 2) not in holidays  # פורים is not in the approved list.
