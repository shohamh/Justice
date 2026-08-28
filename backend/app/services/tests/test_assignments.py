from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import DutyLocation, DutyShift, DutyType, PersonalConstraint, PersonalConstraintOverride
from app.services import assignments as svc
from app.services.settings_loader import set_setting
from tests.helpers import create_soldier


def _seed(session):
    dt = DutyType(name="dt_assign_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_assign_test")
    session.add(dt)
    session.add(loc)
    session.flush()
    return dt, loc


def _approved_constraint(session, soldier_id, start, end):
    c = PersonalConstraint(soldier_id=soldier_id, start_date=start, end_date=end, reason="r", status="approved")
    session.add(c)
    session.flush()
    return c


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


def test_blocks_when_setting_off(admin_session):
    dt, loc = _seed(admin_session)
    soldier = create_soldier(admin_session, personal_number="8400103")
    start, end = date.today(), date.today() + timedelta(days=1)
    _approved_constraint(admin_session, soldier.id, start, end)
    set_setting(admin_session, "constraints.allow_manual_override", False, actor_id=None)

    with pytest.raises(svc.AssignmentError, match="personal_constraint_blocked"):
        svc.create_assignment(
            admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=start, end_date=end,
        )


def test_requires_reason_when_setting_on(admin_session):
    dt, loc = _seed(admin_session)
    soldier = create_soldier(admin_session, personal_number="8400104")
    start, end = date.today(), date.today() + timedelta(days=1)
    _approved_constraint(admin_session, soldier.id, start, end)

    with pytest.raises(svc.AssignmentError, match="override_reason_required"):
        svc.create_assignment(
            admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=start, end_date=end,
        )


def test_succeeds_with_reason_and_writes_audit(admin_session):
    dt, loc = _seed(admin_session)
    soldier = create_soldier(admin_session, personal_number="8400105")
    start, end = date.today(), date.today() + timedelta(days=1)
    constraint = _approved_constraint(admin_session, soldier.id, start, end)

    a = svc.create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start, end_date=end, override_reason="צורך מבצעי",
    )
    admin_session.flush()

    override = admin_session.query(PersonalConstraintOverride).filter(
        PersonalConstraintOverride.personal_constraint_id == constraint.id,
    ).one()
    assert override.soldier_id == soldier.id
    assert override.assignment_kind == "duty"
    assert override.reference_id == a.id
    assert override.reason == "צורך מבצעי"


def test_no_constraint_ignores_override_reason(admin_session):
    dt, loc = _seed(admin_session)
    soldier = create_soldier(admin_session, personal_number="8400106")
    start, end = date.today(), date.today() + timedelta(days=1)

    a = svc.create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start, end_date=end,
    )
    assert a.id is not None
