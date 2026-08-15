from datetime import date, timedelta

from app.scripts.seed import (
    SEED_RANGE_REQUIRED_COUNT,
    SEED_RANGE_RESERVE_COUNT,
    _alal_dates_before_ganash,
)


def test_seed_ranges_use_twenty_five_people_and_five_reserves():
    assert SEED_RANGE_REQUIRED_COUNT == 25
    assert SEED_RANGE_RESERVE_COUNT == 5


def test_alal_demo_dates_are_one_day_before_each_ganash():
    ganash_dates = [date(2026, 8, 6) + timedelta(weeks=week) for week in range(8)]

    assert _alal_dates_before_ganash(ganash_dates) == [
        ganash_date - timedelta(days=1) for ganash_date in ganash_dates
    ]
