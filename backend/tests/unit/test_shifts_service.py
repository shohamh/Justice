from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType
from app.services.shifts import ShiftError, create_shift, delete_shift, list_shifts, update_shift
from tests.helpers import create_soldier


def _dt(session) -> DutyType:
    dt = DutyType(name=f"type_{uuid.uuid4().hex[:6]}", score_per_day=Decimal("1.00"))
    session.add(dt)
    session.flush()
    return dt


def _loc(session) -> DutyLocation:
    loc = DutyLocation(name=f"loc_{uuid.uuid4().hex[:6]}")
    session.add(loc)
    session.flush()
    return loc


def test_create_shift_basic(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
        required_count=2,
    )
    admin_session.commit()
    assert shift.required_count == 2
    assert shift.start_date == date(2026, 7, 1)


def test_create_shift_rejects_bad_dates(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    with pytest.raises(ShiftError, match="end_before_start"):
        create_shift(
            admin_session,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date(2026, 7, 5),
            end_date=date(2026, 7, 1),
        )


def test_create_shift_rejects_zero_duration(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    with pytest.raises(ShiftError, match="end_before_start"):
        create_shift(
            admin_session,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date(2026, 7, 5),
            end_date=date(2026, 7, 5),
        )


def test_fill_status_empty(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 2), required_count=3,
    )
    admin_session.commit()
    from app.services.shifts import get_shift_fill
    result = get_shift_fill(admin_session, shift_id=shift.id)
    assert result.fill_status == "empty"
    assert result.assigned_count == 0


def test_fill_status_partial(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    soldier = create_soldier(admin_session, personal_number=f"sh_{uuid.uuid4().hex[:6]}")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 2), required_count=3,
    )
    admin_session.flush()
    da = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        status="published",
        duty_shift_id=shift.id,
    )
    admin_session.add(da)
    admin_session.commit()
    from app.services.shifts import get_shift_fill
    result = get_shift_fill(admin_session, shift_id=shift.id)
    assert result.fill_status == "partial"
    assert result.assigned_count == 1


def test_delete_fails_with_published_assignments(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    soldier = create_soldier(admin_session, personal_number=f"sh_{uuid.uuid4().hex[:6]}")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 10, 1), end_date=date(2026, 10, 2),
    )
    admin_session.flush()
    da = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
        status="published",
        duty_shift_id=shift.id,
    )
    admin_session.add(da)
    admin_session.commit()
    with pytest.raises(ShiftError, match="has_assignments"):
        delete_shift(admin_session, shift=shift)


def test_fill_status_excludes_reserve(admin_session):
    """fill_status and assigned_count must be based on primary assignments only, not reserve."""
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    soldier_primary = create_soldier(admin_session, personal_number=f"sh_{uuid.uuid4().hex[:6]}")
    soldier_reserve = create_soldier(admin_session, personal_number=f"sh_{uuid.uuid4().hex[:6]}")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 7, 10), end_date=date(2026, 7, 11), required_count=2,
    )
    admin_session.flush()
    # Add 1 primary + 1 reserve assignment
    da_primary = DutyAssignment(
        soldier_id=soldier_primary.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
        status="published",
        duty_shift_id=shift.id,
        is_reserve=False,
    )
    da_reserve = DutyAssignment(
        soldier_id=soldier_reserve.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
        status="published",
        duty_shift_id=shift.id,
        is_reserve=True,
    )
    admin_session.add(da_primary)
    admin_session.add(da_reserve)
    admin_session.commit()
    from app.services.shifts import get_shift_fill
    result = get_shift_fill(admin_session, shift_id=shift.id)
    # With 2 required, 1 primary → partial (reserve should not count)
    assert result.fill_status == "partial", f"expected 'partial', got '{result.fill_status}'"
    assert result.assigned_count == 1, f"expected 1 primary, got {result.assigned_count}"
    assert result.reserve_assigned_count == 1


def test_list_shifts_date_filter(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift_in = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 5),
    )
    shift_out = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 12, 1), end_date=date(2026, 12, 5),
    )
    admin_session.commit()
    results = list_shifts(admin_session, date_from=date(2026, 11, 1), date_to=date(2026, 11, 30))
    ids = [r.id for r in results]
    assert shift_in.id in ids
    assert shift_out.id not in ids
