from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation, DutyShift, DutyType
from app.services import assignments as svc
from tests.helpers import create_soldier


def _seed(session):
    dt = DutyType(name="dt_assign_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_assign_test")
    session.add(dt)
    session.add(loc)
    session.flush()
    return dt, loc


def test_create_assignment_without_shift_defaults_to_full_day_times(admin_session):
    dt, loc = _seed(admin_session)
    soldier = create_soldier(admin_session, personal_number="8400101")
    a = svc.create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    assert a.start_time == "00:00"
    assert a.end_time == "23:59"


def test_create_assignment_copies_times_from_linked_shift(admin_session):
    dt, loc = _seed(admin_session)
    soldier = create_soldier(admin_session, personal_number="8400102")
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        start_time="08:00", end_time="17:00",
    )
    admin_session.add(shift)
    admin_session.flush()
    a = svc.create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=shift.start_date, end_date=shift.end_date, duty_shift_id=shift.id,
    )
    assert a.start_time == "08:00"
    assert a.end_time == "17:00"
