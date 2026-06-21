from datetime import date

import pytest

from app.db.models import DutyLocation, DutyShift, DutyType
from app.services import shift_templates as svc
from app.services import shifts as shifts_svc


def _seed_type_and_location(session):
    dt = DutyType(name="שמירה-gen", score_per_day=1)
    loc = DutyLocation(name="עמדה-gen")
    session.add(dt)
    session.add(loc)
    session.flush()
    return dt, loc


def test_generate_creates_one_shift_per_matching_day(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="t1", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1, 3, 5], required_count=2,
    )
    admin_session.flush()
    created = svc.generate_shifts(
        admin_session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 7),
    )
    assert len(created) == 3  # Mon, Wed, Fri
    assert all(s.required_count == 2 for s in created)
    assert all(s.generated_from_template_id == tpl.id for s in created)


def test_generate_is_idempotent(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="t2", duty_type_id=dt.id, duty_location_id=loc.id, weekdays=[1],
    )
    admin_session.flush()
    first = svc.generate_shifts(admin_session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 14))
    admin_session.flush()
    second = svc.generate_shifts(admin_session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 14))
    assert len(first) == 2   # two Mondays
    assert len(second) == 0  # already present → no duplicates


def test_preview_reports_existing_vs_new(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="t3", duty_type_id=dt.id, duty_location_id=loc.id, weekdays=[1],
    )
    admin_session.flush()
    svc.generate_shifts(admin_session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 1))
    admin_session.flush()
    preview = svc.preview_generation(admin_session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 8))
    new_dates = [p["date"] for p in preview if not p["exists"]]
    existing_dates = [p["date"] for p in preview if p["exists"]]
    assert date(2026, 6, 8) in new_dates
    assert date(2026, 6, 1) in existing_dates


def test_roll_horizon_generates_only_for_auto_roll_templates(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    rolling = svc.create_template(
        admin_session, name="auto", duty_type_id=dt.id, duty_location_id=loc.id, weekdays=[1,2,3,4,5,6,7], auto_roll=True,
    )
    manual = svc.create_template(
        admin_session, name="manual", duty_type_id=dt.id, duty_location_id=loc.id, weekdays=[1,2,3,4,5,6,7], auto_roll=False,
    )
    admin_session.flush()
    total = svc.roll_horizon(admin_session, horizon_days=10, today=date(2026, 6, 1))
    assert total == 10  # 10 days, every weekday, only the auto_roll template
    rolled = admin_session.query(DutyShift).filter(DutyShift.generated_from_template_id == rolling.id).count()
    not_rolled = admin_session.query(DutyShift).filter(DutyShift.generated_from_template_id == manual.id).count()
    assert rolled == 10
    assert not_rolled == 0


from decimal import Decimal as _Decimal
from app.db.models import DutyLocation as _DL, DutyType as _DT, DutyShift as _DS
from app.services.algorithm_bridge import reserve_count_for_shift


def test_reserve_count_formula(admin_session):
    dt = _DT(name="שמירה-rc", score_per_day=_Decimal("1"), reserve_ratio=_Decimal("0.200"), reserve_minimum=0)
    loc = _DL(name="עמדה-rc")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = _DS(duty_type_id=dt.id, duty_location_id=loc.id,
                start_date=date(2026,6,1), end_date=date(2026,6,1), required_count=20)
    admin_session.add(shift); admin_session.flush()
    assert reserve_count_for_shift(admin_session, shift=shift) == 4


def test_reserve_count_minimum(admin_session):
    dt = _DT(name="שמירה-rmin", score_per_day=_Decimal("1"), reserve_ratio=_Decimal("0.100"), reserve_minimum=3)
    loc = _DL(name="עמדה-rmin")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = _DS(duty_type_id=dt.id, duty_location_id=loc.id,
                start_date=date(2026,6,1), end_date=date(2026,6,1), required_count=5)
    admin_session.add(shift); admin_session.flush()
    assert reserve_count_for_shift(admin_session, shift=shift) == 3


def test_reserve_count_override(admin_session):
    dt = _DT(name="שמירה-rov", score_per_day=_Decimal("1"), reserve_ratio=_Decimal("0.200"), reserve_minimum=0)
    loc = _DL(name="עמדה-rov")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = _DS(duty_type_id=dt.id, duty_location_id=loc.id,
                start_date=date(2026,6,1), end_date=date(2026,6,1), required_count=20, reserve_count_override=7)
    admin_session.add(shift); admin_session.flush()
    assert reserve_count_for_shift(admin_session, shift=shift) == 7


def test_create_template_rejects_past_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    with pytest.raises(svc.TemplateError):
        svc.create_template(
            admin_session, name="bad", duty_type_id=dt.id, duty_location_id=loc.id,
            weekdays=[1], auto_roll=True, auto_roll_until=date(2020, 1, 1),
        )


def test_create_template_stores_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="future", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1], auto_roll=True, auto_roll_until=date(2099, 1, 1),
    )
    assert tpl.auto_roll_until == date(2099, 1, 1)


def test_update_template_can_clear_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="clearme", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1], auto_roll=True, auto_roll_until=date(2099, 1, 1),
    )
    admin_session.flush()
    svc.update_template(admin_session, tpl=tpl, auto_roll_until=None)
    assert tpl.auto_roll_until is None


def test_roll_horizon_clamps_to_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="clamped", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1, 2, 3, 4, 5, 6, 7], auto_roll=True,
    )
    tpl.auto_roll_until = date(2026, 6, 5)
    admin_session.flush()
    total = svc.roll_horizon(admin_session, horizon_days=10, today=date(2026, 6, 1))
    assert total == 5  # Jun 1..5 inclusive, clamped well before the 10-day horizon end (Jun 10)
    rolled = admin_session.query(DutyShift).filter(DutyShift.generated_from_template_id == tpl.id).count()
    assert rolled == 5


def test_roll_horizon_skips_template_past_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="expired", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1, 2, 3, 4, 5, 6, 7], auto_roll=True,
    )
    tpl.auto_roll_until = date(2026, 5, 1)
    admin_session.flush()
    total = svc.roll_horizon(admin_session, horizon_days=10, today=date(2026, 6, 1))
    assert total == 0
    rolled = admin_session.query(DutyShift).filter(DutyShift.generated_from_template_id == tpl.id).count()
    assert rolled == 0


def test_create_template_rejects_end_time_before_start_time_when_single_day(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    with pytest.raises(svc.TemplateError):
        svc.create_template(
            admin_session, name="bad_order", duty_type_id=dt.id, duty_location_id=loc.id,
            recurrence_type="daily", weekdays=[], duration_days=1,
            start_time="17:00", end_time="08:00",
        )


def test_create_template_allows_any_end_time_when_multi_day(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="overnight_multi", duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="daily", weekdays=[], duration_days=2,
        start_time="23:00", end_time="01:00",
    )
    assert tpl.duration_days == 2


def test_generate_shifts_copies_template_times_onto_shift(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="timed", duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="daily", weekdays=[], duration_days=1,
        start_time="08:00", end_time="17:00",
    )
    admin_session.flush()
    created = svc.generate_shifts(
        admin_session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 1),
    )
    assert len(created) == 1
    assert created[0].start_time == "08:00"
    assert created[0].end_time == "17:00"


def test_create_shift_defaults_to_full_day_times(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    shift = shifts_svc.create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    assert shift.start_time == "00:00"
    assert shift.end_time == "23:59"


def test_create_shift_accepts_explicit_times(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    shift = shifts_svc.create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        start_time="08:00", end_time="17:00",
    )
    assert shift.start_time == "08:00"
    assert shift.end_time == "17:00"


def test_create_shift_rejects_end_time_before_start_time_when_single_day(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    with pytest.raises(shifts_svc.ShiftError):
        shifts_svc.create_shift(
            admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
            start_time="17:00", end_time="08:00",
        )


def test_create_shift_rejects_malformed_time_format(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    with pytest.raises(shifts_svc.ShiftError):
        shifts_svc.create_shift(
            admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
            start_time="8:00", end_time="17:00",
        )
