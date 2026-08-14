from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import delete, text

from app.db.models import DutyLocation, DutyType
from app.services import calendar_shifts
from app.services.assignments import create_assignment
from app.services.duty_config import create_duty_type
from app.services.shifts import create_shift
from tests.helpers import create_node, create_soldier


def _make_duty_type_and_location(session, name_suffix: str):
    dt = create_duty_type(session, name=f"dt_calshift_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_calshift_{name_suffix}")
    session.add(loc)
    session.flush()
    return dt, loc


def _orphan_duty_type(session, dt: DutyType) -> None:
    """Delete a DutyType row while a shift still references it, simulating a
    dangling duty_type_id (e.g. historical data drift / an out-of-band admin
    operation). The FK is ON DELETE RESTRICT (a duty type in use can't
    normally be deleted), so we briefly relax constraint enforcement for this
    session only, forcing the orphaned state.

    `SET session_replication_role = 'replica'` is session-scoped (not a
    table-wide DDL toggle like `ALTER TABLE ... DISABLE TRIGGER ALL`), so if
    something crashes between the SET and the `finally`'s reset, the only
    lasting effect is a dead session that gets torn down normally — no
    persistent DB-level artifact survives for other tests in the same pooled
    Postgres instance.
    """
    session.execute(text("SET session_replication_role = 'replica'"))
    try:
        session.execute(delete(DutyType).where(DutyType.id == dt.id))
        session.flush()
    finally:
        session.execute(text("SET session_replication_role = 'origin'"))


def test_single_shift_with_missing_duty_type_gets_hash_color_not_black(admin_session):
    dt, loc = _make_duty_type_and_location(admin_session, "1")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    admin_session.commit()

    _orphan_duty_type(admin_session, dt)

    row = calendar_shifts.get_single_shift(admin_session, shift_id=shift.id)
    assert row is not None
    assert row["duty_type_color"] != ""
    assert row["duty_type_color"].startswith("hsl(")


def test_calendar_shifts_with_missing_duty_type_gets_hash_color_not_black(admin_session):
    node = create_node(admin_session, level="division", name="div_calshift2")
    create_soldier(admin_session, personal_number="calshift2-1", hierarchy_node_id=node.id)
    dt, loc = _make_duty_type_and_location(admin_session, "2")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    admin_session.commit()

    _orphan_duty_type(admin_session, dt)

    rows = calendar_shifts.get_calendar_shifts(
        admin_session, node_id=node.id, date_from=date(2026, 6, 1), date_to=date(2026, 6, 2),
    )
    by_id = {r["id"]: r for r in rows}
    assert shift.id in by_id
    assert by_id[shift.id]["duty_type_color"] != ""
    assert by_id[shift.id]["duty_type_color"].startswith("hsl(")


def test_calendar_shifts_hides_shift_filled_entirely_outside_subtree(admin_session):
    node_a = create_node(admin_session, level="division", name="div_calshift3_a")
    node_b = create_node(admin_session, level="division", name="div_calshift3_b")
    soldier_b = create_soldier(admin_session, personal_number="calshift3-b", hierarchy_node_id=node_b.id)
    dt, loc = _make_duty_type_and_location(admin_session, "3")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    create_assignment(
        admin_session, soldier_id=soldier_b.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), duty_shift_id=shift.id,
    )
    admin_session.commit()

    # Viewed from node_b (the assignee's own subtree), the shift is visible.
    rows_b = calendar_shifts.get_calendar_shifts(
        admin_session, node_id=node_b.id, date_from=date(2026, 6, 1), date_to=date(2026, 6, 2),
    )
    assert shift.id in {r["id"] for r in rows_b}

    # Viewed from an unrelated subtree, the shift (filled entirely by someone
    # outside it) should be filtered out.
    rows_a = calendar_shifts.get_calendar_shifts(
        admin_session, node_id=node_a.id, date_from=date(2026, 6, 1), date_to=date(2026, 6, 2),
    )
    assert shift.id not in {r["id"] for r in rows_a}
