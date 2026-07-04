from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation, DutyShift, DutyType
from app.services.algorithm_bridge import load_duty_blocks_from_shifts


def _dt(session, name=None) -> DutyType:
    dt = DutyType(name=name or f"dt_{uuid.uuid4().hex[:6]}", score_per_day=Decimal("2.00"))
    session.add(dt)
    session.flush()
    return dt


def _loc(session) -> DutyLocation:
    loc = DutyLocation(name=f"loc_{uuid.uuid4().hex[:6]}")
    session.add(loc)
    session.flush()
    return loc


def _shift(session, dt, loc, start, end, count=1) -> DutyShift:
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start,
        end_date=end,
        required_count=count,
    )
    session.add(shift)
    session.flush()
    return shift


def test_single_shift_required_count_1(admin_session):
    from datetime import timedelta
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    start = date.today() + timedelta(days=1)
    end = date.today() + timedelta(days=3)
    shift = _shift(admin_session, dt, loc, start, end, count=1)
    admin_session.commit()

    blocks, b2s = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 1
    assert blocks[0].duty_type_id == dt.id
    assert blocks[0].start_date == start
    assert b2s[blocks[0].id] == shift.id


def test_shift_expands_to_N_blocks(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = _shift(admin_session, dt, loc, date(2026, 8, 1), date(2026, 8, 2), count=4)
    admin_session.commit()

    blocks, b2s = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 4
    for b in blocks:
        assert b2s[b.id] == shift.id


def test_block_copies_shift_times_when_not_truncated(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 2),
        start_time="08:00", end_time="17:00", required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 1
    assert blocks[0].start_time == "08:00"
    assert blocks[0].end_time == "17:00"


def test_block_start_time_resets_to_midnight_when_truncated_to_today(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    from datetime import timedelta
    yesterday = date.today() - timedelta(days=1)
    far_future = date.today() + timedelta(days=5)
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=yesterday, end_date=far_future,
        start_time="08:00", end_time="17:00", required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 1
    assert blocks[0].start_date == date.today()  # truncated forward
    assert blocks[0].start_time == "00:00"        # NOT "08:00" -- that was yesterday's clock time
    assert blocks[0].end_time == "17:00"           # end side is never truncated, unaffected


def test_multiple_shifts_combined(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    s1 = _shift(admin_session, dt, loc, date(2026, 9, 1), date(2026, 9, 2), count=2)
    s2 = _shift(admin_session, dt, loc, date(2026, 9, 2), date(2026, 9, 3), count=3)
    admin_session.commit()

    blocks, b2s = load_duty_blocks_from_shifts(admin_session, shift_ids=[s1.id, s2.id])
    assert len(blocks) == 5
    assert len([b for b in blocks if b2s[b.id] == s1.id]) == 2
    assert len([b for b in blocks if b2s[b.id] == s2.id]) == 3


def test_block_ids_are_unique(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = _shift(admin_session, dt, loc, date(2026, 10, 1), date(2026, 10, 2), count=5)
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len({b.id for b in blocks}) == 5


def test_score_per_day_from_duty_type(admin_session):
    dt = DutyType(name=f"exp_{uuid.uuid4().hex[:6]}", score_per_day=Decimal("5.50"))
    loc = _loc(admin_session)
    admin_session.add(dt)
    admin_session.flush()
    shift = _shift(admin_session, dt, loc, date(2026, 11, 1), date(2026, 11, 2), count=1)
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert blocks[0].score_per_day == Decimal("5.50")
