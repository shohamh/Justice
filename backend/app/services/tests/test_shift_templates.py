import uuid
from datetime import date
from datetime import date as _date
from decimal import Decimal

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type
from app.services.shift_templates import create_template, expand_dates, generate_shifts, update_template
from tests.helpers import create_node


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_duty_type_and_location(session):
    dt = create_duty_type(session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    session.add(loc)
    session.flush()
    return dt, loc


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


def test_create_template_with_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_tpl1")
    dt, loc = _make_duty_type_and_location(admin_session)
    tpl = create_template(
        admin_session, name="tpl_scoped", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1], eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert tpl.eligible_node_ids == [node.id]


def test_update_template_clears_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_tpl2")
    dt, loc = _make_duty_type_and_location(admin_session)
    tpl = create_template(
        admin_session, name="tpl_clear", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1], eligible_node_ids=[node.id],
    )
    admin_session.commit()

    update_template(admin_session, tpl=tpl, eligible_node_ids=None)
    admin_session.commit()
    assert tpl.eligible_node_ids is None


def test_generate_shifts_copies_template_scope_onto_each_shift(admin_session):
    node = create_node(admin_session, level="division", name="div_tpl3")
    dt, loc = _make_duty_type_and_location(admin_session)
    tpl = create_template(
        admin_session, name="tpl_generate_scope", duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="daily", weekdays=[], eligible_node_ids=[node.id],
    )
    admin_session.commit()

    created = generate_shifts(admin_session, tpl=tpl, range_start=_date(2026, 6, 1), range_end=_date(2026, 6, 1))
    admin_session.commit()
    assert len(created) == 1
    assert created[0].eligible_node_ids == [node.id]
