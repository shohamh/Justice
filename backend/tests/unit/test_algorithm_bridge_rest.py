from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import (
    DutyAssignment, DutyDismissal, DutyLocation, DutyShift, DutyType, SystemSetting,
)
from app.services.algorithm_bridge import load_duty_blocks_from_shifts, load_existing_assignments
from tests.helpers import create_soldier


def test_load_duty_blocks_uses_type_override(admin_session):
    dt = DutyType(name="dt-rest-a", score_per_day=Decimal("1.00"), requirements={"rest_hours": 8})
    loc = DutyLocation(name="loc-rest-a")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2), required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 1
    assert blocks[0].rest_hours == 8


def test_load_duty_blocks_uses_global_default(admin_session):
    admin_session.merge(SystemSetting(key="duty.default_rest_hours", value=12))
    dt = DutyType(name="dt-rest-b", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="loc-rest-b")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2), required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert blocks[0].rest_hours == 12


def test_load_existing_assignments_populates_effective_end(admin_session):
    dt = DutyType(name="dt-rest-c", score_per_day=Decimal("1.00"), requirements={"rest_hours": 10})
    loc = DutyLocation(name="loc-rest-c")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    s = create_soldier(admin_session, personal_number="8109001")
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 4),
        start_time="08:00", end_time="17:00", status="published",
    )
    admin_session.add(a)
    admin_session.flush()

    existing = load_existing_assignments(
        admin_session, planning_start=date(2026, 9, 1), planning_end=date(2026, 9, 10), W=14,
    )
    assert len(existing) == 1
    ea = existing[0]
    assert ea.rest_hours == 10
    assert ea.rest_effective_end_date == date(2026, 9, 3)
    assert ea.rest_effective_end_time == "17:00"


def test_load_existing_assignments_uses_dismissal_effective_end(admin_session):
    dt = DutyType(name="dt-rest-d", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="loc-rest-d")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    s = create_soldier(admin_session, personal_number="8109002")
    a = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 5),
        start_time="08:00", end_time="17:00", status="published",
    )
    admin_session.add(a)
    admin_session.flush()
    admin_session.add(DutyDismissal(
        duty_assignment_id=a.id, dismissed_from=date(2026, 9, 3), dismissed_to=date(2026, 9, 4),
    ))
    admin_session.flush()

    existing = load_existing_assignments(
        admin_session, planning_start=date(2026, 9, 1), planning_end=date(2026, 9, 10), W=14,
    )
    ea = existing[0]
    assert ea.rest_effective_end_date == date(2026, 9, 3)
    assert ea.rest_effective_end_time == "08:00"
