from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, event, text
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, SystemSetting
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
    soldier = create_soldier(admin_session, personal_number="calshift2-1", hierarchy_node_id=node.id)
    dt, loc = _make_duty_type_and_location(admin_session, "2")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), duty_shift_id=shift.id,
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


def test_hierarchy_calendar_reads_display_data_with_matching_assignments(admin_session):
    node = create_node(admin_session, level="division", name="calendar-assignment-scope")
    soldier = create_soldier(
        admin_session,
        personal_number="calendar-assignment-scope",
        hierarchy_node_id=node.id,
        full_name="Visible Soldier",
    )
    soldier.profile_picture_url = "https://example.invalid/calendar-soldier.png"
    _unused_soldier = create_soldier(
        admin_session,
        personal_number="calendar-assignment-scope-unused",
        hierarchy_node_id=node.id,
    )
    dt, loc = _make_duty_type_and_location(admin_session, "assignment-scope")
    day = date(2026, 6, 1)
    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=day,
        end_date=day + timedelta(days=1),
    )
    create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=day,
        end_date=day + timedelta(days=1),
        duty_shift_id=shift.id,
    )
    admin_session.commit()

    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    engine = admin_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        rows = calendar_shifts.get_calendar_shifts(
            admin_session,
            node_id=node.id,
            date_from=day,
            date_to=day,
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)

    matching_assignment_reads = [
        statement
        for statement in statements
        if " from duty_assignments join soldiers " in statement
    ]
    assert matching_assignment_reads
    assert not any(" from soldiers " in statement for statement in statements)
    assert len(rows) == 1
    assert rows[0]["assignees"][0]["soldier_id"] == soldier.id
    assert rows[0]["assignees"][0]["soldier_name"] == "Visible Soldier"
    assert rows[0]["assignees"][0]["hierarchy_label"] == node.name
    assert rows[0]["assignees"][0]["hierarchy_path_ids"] == [str(node.id)]
    assert rows[0]["assignees"][0]["profile_picture_url"] == soldier.profile_picture_url


def test_hierarchy_calendar_omits_inactive_assignees(admin_session):
    node = create_node(admin_session, level="division", name="calendar-inactive-assignee")
    active = create_soldier(
        admin_session, personal_number="calendar-active-assignee", hierarchy_node_id=node.id
    )
    inactive = create_soldier(
        admin_session, personal_number="calendar-inactive-assignee", hierarchy_node_id=node.id
    )
    inactive.left_at = date(2026, 5, 31)
    dt, loc = _make_duty_type_and_location(admin_session, "inactive-assignee")
    day = date(2026, 6, 1)
    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=day,
        end_date=day + timedelta(days=1),
    )
    for soldier in (active, inactive):
        create_assignment(
            admin_session,
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=day,
            end_date=day + timedelta(days=1),
            duty_shift_id=shift.id,
        )
    admin_session.commit()

    rows = calendar_shifts.get_calendar_shifts(
        admin_session,
        node_id=node.id,
        date_from=day,
        date_to=day,
    )

    assert len(rows) == 1
    assert [assignee["soldier_id"] for assignee in rows[0]["assignees"]] == [active.id]


def test_personal_calendar_includes_departed_soldiers_assignments(admin_session):
    node = create_node(admin_session, level="division", name="calendar-departed-personal")
    soldier = create_soldier(
        admin_session, personal_number="calendar-departed-personal", hierarchy_node_id=node.id
    )
    soldier.left_at = date(2026, 5, 31)
    dt, loc = _make_duty_type_and_location(admin_session, "departed-personal")
    day = date(2026, 6, 1)
    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=day,
        end_date=day + timedelta(days=1),
    )
    create_assignment(
        admin_session,
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=day,
        end_date=day + timedelta(days=1),
        duty_shift_id=shift.id,
    )
    admin_session.commit()

    rows = calendar_shifts.get_calendar_shifts(
        admin_session,
        soldier_id=soldier.id,
        date_from=day,
        date_to=day,
    )

    assert len(rows) == 1
    assert rows[0]["assignees"][0]["soldier_id"] == soldier.id


def test_framework_calendar_includes_unassigned_shifts(admin_session):
    root = create_node(admin_session, level="corps", name="calendar-framework-root")
    unit = create_node(admin_session, level="team", name="calendar-framework-team", parent=root)
    member = create_soldier(
        admin_session, personal_number="calendar-framework-member", hierarchy_node_id=unit.id
    )
    admin_session.merge(SystemSetting(key="system.root_node_id", value=str(root.id), updated_by=None))
    dt, loc = _make_duty_type_and_location(admin_session, "framework-unassigned")
    day = date(2026, 6, 1)
    assigned_shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=day,
        end_date=day + timedelta(days=1),
    )
    open_shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=day,
        end_date=day + timedelta(days=1),
    )
    create_assignment(
        admin_session,
        soldier_id=member.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=day,
        end_date=day + timedelta(days=1),
        duty_shift_id=assigned_shift.id,
    )
    admin_session.commit()

    rows = calendar_shifts.get_calendar_shifts(
        admin_session,
        node_id=root.id,
        date_from=day,
        date_to=day,
    )

    assert {row["id"] for row in rows} == {assigned_shift.id, open_shift.id}
    assert next(row for row in rows if row["id"] == open_shift.id)["assignees"] == []


def test_calendar_shift_list_queries_stay_bounded_as_shift_count_grows(admin_session):
    node = create_node(admin_session, level="division", name="calendar-query-shape")
    soldier = create_soldier(
        admin_session, personal_number="calendar-query-shape", hierarchy_node_id=node.id
    )
    location = DutyLocation(name="calendar-query-shape")
    admin_session.add(location)
    admin_session.flush()
    first_day = date.today() + timedelta(days=10)
    shift_ids = []
    for offset in range(6):
        duty_type = DutyType(
            name=f"calendar-query-shape-{offset}", score_per_day=Decimal("1.00"),
            reserve_ratio=Decimal("0.500"), reserve_minimum=2,
        )
        admin_session.add(duty_type)
        admin_session.flush()
        day = first_day + timedelta(days=offset)
        shift = DutyShift(
            duty_type_id=duty_type.id, duty_location_id=location.id,
            start_date=day, end_date=day + timedelta(days=1),
            required_count=3, status="active",
            reserve_count_override=4 if offset == 2 else None,
        )
        admin_session.add(shift)
        admin_session.flush()
        shift_ids.append(shift.id)
        admin_session.add(DutyAssignment(
            soldier_id=soldier.id, duty_type_id=duty_type.id,
            duty_location_id=location.id, duty_shift_id=shift.id,
            start_date=day, end_date=day + timedelta(days=1), status="published",
        ))
    admin_session.commit()

    def load_and_count(last_day):
        statements = []

        def record(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        engine = admin_session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            with Session(bind=engine) as read_session:
                rows = calendar_shifts.get_calendar_shifts(
                    read_session, node_id=node.id, date_from=first_day, date_to=last_day,
                )
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return rows, len(statements)

    one_row, one_query_count = load_and_count(first_day)
    all_rows, all_query_count = load_and_count(first_day + timedelta(days=5))

    assert {row["id"] for row in one_row} == {shift_ids[0]}
    assert {row["id"] for row in all_rows} == set(shift_ids)
    assert {row["id"]: row["reserve_required_count"] for row in all_rows} == {
        shift_id: (4 if index == 2 else 2) for index, shift_id in enumerate(shift_ids)
    }
    assert all_query_count <= one_query_count + 2
