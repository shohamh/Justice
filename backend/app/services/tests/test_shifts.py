from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type
from app.services.shifts import create_shift, get_shift_fill, list_shifts
from tests.helpers import create_node


def _make_duty_type_and_location(session, name_suffix: str):
    dt = create_duty_type(session, name=f"dt_shift_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_shift_{name_suffix}")
    session.add(loc)
    session.flush()
    return dt, loc


def test_create_shift_with_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_shift1")
    dt, loc = _make_duty_type_and_location(admin_session, "1")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert shift.eligible_node_ids == [node.id]


def test_get_shift_fill_exposes_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_shift2")
    dt, loc = _make_duty_type_and_location(admin_session, "2")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    fill = get_shift_fill(admin_session, shift_id=shift.id)
    assert fill is not None
    assert fill.eligible_node_ids == [node.id]


def test_list_shifts_exposes_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_shift3")
    dt, loc = _make_duty_type_and_location(admin_session, "3")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    results = list_shifts(admin_session, date_from=date(2026, 6, 1), date_to=date(2026, 6, 1))
    by_id = {s.id: s for s in results}
    assert by_id[shift.id].eligible_node_ids == [node.id]


def test_create_shift_with_explicit_overnight_hours_extends_end_date(admin_session):
    # The frontend always sends explicit start_time/end_time (inherited from
    # the duty type, but editable); when they cross midnight for a single
    # selected day, the shift should still be stretched to cover the night
    # rather than rejected as an invalid time order.
    dt, loc = _make_duty_type_and_location(admin_session, "4")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        start_time="22:00", end_time="06:00",
    )
    admin_session.commit()
    assert shift.end_date == date(2026, 6, 3)
    assert shift.start_time == "22:00"
    assert shift.end_time == "06:00"
