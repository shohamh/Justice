from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyType,
    RangeAssignment,
    RangeEvent,
    RangeEventStatus,
    RangeType,
    SoldierRangeQualification,
)
from app.services.ineligible_soldiers import list_ineligible_soldiers
from tests.helpers import create_duty_location, create_node, create_range_location, create_soldier

AS_OF = date(2026, 8, 15)


def _duty_type(session: Session, *, name: str, required_range_type: RangeType | None) -> DutyType:
    duty_type = DutyType(
        name=name,
        score_per_day=Decimal("1.00"),
        requires_weapon=required_range_type is not None,
        required_range_type=required_range_type,
    )
    session.add(duty_type)
    session.flush()
    return duty_type


def _duty(
    session: Session,
    *,
    soldier_id,
    duty_type: DutyType,
    start_date: date,
    status: str = "published",
) -> DutyAssignment:
    assignment = DutyAssignment(
        soldier_id=soldier_id,
        duty_type_id=duty_type.id,
        duty_location_id=create_duty_location(session).id,
        start_date=start_date,
        end_date=start_date,
        status=status,
    )
    session.add(assignment)
    session.flush()
    return assignment


def _range_assignment(
    session: Session,
    *,
    soldier_id,
    node_id,
    range_type: RangeType,
    event_date: date,
    status: RangeEventStatus = RangeEventStatus.planned,
    is_draft: bool = False,
) -> RangeEvent:
    event = RangeEvent(
        hierarchy_node_id=node_id,
        range_type=range_type,
        date=event_date,
        range_location_id=create_range_location(session).id,
        required_count=1,
        status=status,
    )
    session.add(event)
    session.flush()
    session.add(RangeAssignment(range_event_id=event.id, soldier_id=soldier_id, is_draft=is_draft))
    session.flush()
    return event


def test_lists_only_soldiers_without_a_qualification_valid_today(app_session: Session) -> None:
    root = create_node(app_session, level="branch", name="Root")
    child = create_node(app_session, level="company", name="Child", parent=root)
    sibling = create_node(app_session, level="company", name="Sibling", parent=root)
    unqualified = create_soldier(app_session, personal_number="inq-001", hierarchy_node_id=child.id)
    expired = create_soldier(app_session, personal_number="inq-002", hierarchy_node_id=child.id)
    valid_on_boundary = create_soldier(
        app_session, personal_number="inq-003", hierarchy_node_id=sibling.id
    )
    valid_later = create_soldier(
        app_session, personal_number="inq-004", hierarchy_node_id=sibling.id
    )
    profile_mitvachim = create_soldier(
        app_session, personal_number="inq-006", hierarchy_node_id=child.id
    )
    profile_alal = create_soldier(
        app_session, personal_number="inq-007", hierarchy_node_id=child.id
    )
    outside = create_soldier(app_session, personal_number="inq-005")
    profile_mitvachim.last_mitvahim_date = AS_OF - timedelta(days=5)
    profile_alal.last_alal_date = AS_OF - timedelta(days=5)
    app_session.add_all(
        [
            SoldierRangeQualification(
                soldier_id=expired.id,
                range_type=RangeType.laser,
                valid_until=AS_OF - timedelta(days=1),
            ),
            SoldierRangeQualification(
                soldier_id=valid_on_boundary.id, range_type=RangeType.live, valid_until=AS_OF
            ),
            SoldierRangeQualification(
                soldier_id=valid_later.id,
                range_type=RangeType.alal,
                valid_until=AS_OF + timedelta(days=1),
            ),
        ]
    )
    app_session.commit()

    records = list_ineligible_soldiers(app_session, roots=None, as_of=AS_OF)

    assert [record.soldier_id for record in records] == [unqualified.id, expired.id]
    assert records[0].soldier_name == unqualified.full_name
    assert records[0].personal_number == unqualified.personal_number
    assert records[0].hierarchy_node_id == child.id
    assert records[0].hierarchy_path_ids == tuple(child.path_ids)
    assert records[0].valid_qualifications == ()
    assert outside.id not in {record.soldier_id for record in records}


def test_overlapping_roots_return_each_soldier_once(app_session: Session) -> None:
    root = create_node(app_session, level="branch", name="Root")
    child = create_node(app_session, level="company", name="Child", parent=root)
    sibling = create_node(app_session, level="company", name="Sibling", parent=root)
    other_root = create_node(app_session, level="branch", name="Other")
    child_soldier = create_soldier(
        app_session, personal_number="inq-101", hierarchy_node_id=child.id
    )
    sibling_soldier = create_soldier(
        app_session, personal_number="inq-102", hierarchy_node_id=sibling.id
    )
    outside_soldier = create_soldier(
        app_session, personal_number="inq-103", hierarchy_node_id=other_root.id
    )

    records = list_ineligible_soldiers(app_session, roots={root.id, child.id}, as_of=AS_OF)

    assert {record.soldier_id for record in records} == {child_soldier.id, sibling_soldier.id}
    assert len(records) == 2
    assert outside_soldier.id not in {record.soldier_id for record in records}


def test_future_weapon_duty_without_matching_range_is_urgent(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="Root")
    laser_duty = _duty_type(app_session, name="Laser duty", required_range_type=RangeType.laser)
    non_weapon_duty = _duty_type(app_session, name="Desk duty", required_range_type=None)
    urgent = create_soldier(app_session, personal_number="inq-201", hierarchy_node_id=node.id)
    covered = create_soldier(app_session, personal_number="inq-202", hierarchy_node_id=node.id)
    non_weapon = create_soldier(app_session, personal_number="inq-203", hierarchy_node_id=node.id)
    cancelled_duty = create_soldier(
        app_session, personal_number="inq-204", hierarchy_node_id=node.id
    )
    draft_range = create_soldier(app_session, personal_number="inq-205", hierarchy_node_id=node.id)
    _duty(app_session, soldier_id=urgent.id, duty_type=laser_duty, start_date=AS_OF)
    _duty(
        app_session,
        soldier_id=covered.id,
        duty_type=laser_duty,
        start_date=AS_OF + timedelta(days=1),
    )
    _duty(app_session, soldier_id=non_weapon.id, duty_type=non_weapon_duty, start_date=AS_OF)
    _duty(
        app_session,
        soldier_id=cancelled_duty.id,
        duty_type=laser_duty,
        start_date=AS_OF,
        status="cancelled",
    )
    _duty(app_session, soldier_id=draft_range.id, duty_type=laser_duty, start_date=AS_OF)
    _range_assignment(
        app_session,
        soldier_id=urgent.id,
        node_id=node.id,
        range_type=RangeType.live,
        event_date=AS_OF,
    )
    _range_assignment(
        app_session,
        soldier_id=covered.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF,
    )
    _range_assignment(
        app_session,
        soldier_id=covered.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF + timedelta(days=1),
        status=RangeEventStatus.cancelled,
    )
    _range_assignment(
        app_session,
        soldier_id=draft_range.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF,
        is_draft=True,
    )
    app_session.commit()

    by_soldier = {
        record.soldier_id: record
        for record in list_ineligible_soldiers(app_session, roots={node.id}, as_of=AS_OF)
    }

    assert by_soldier[urgent.id].has_upcoming_weapon_duty is True
    assert by_soldier[urgent.id].has_upcoming_matching_range is False
    assert by_soldier[urgent.id].upcoming_weapon_duties[0].start_date == AS_OF
    assert by_soldier[urgent.id].upcoming_matching_ranges == ()
    assert by_soldier[covered.id].has_upcoming_matching_range is True
    assert by_soldier[covered.id].upcoming_matching_ranges[0].range_type == RangeType.laser
    assert by_soldier[non_weapon.id].has_upcoming_weapon_duty is False
    assert by_soldier[cancelled_duty.id].has_upcoming_weapon_duty is False
    assert by_soldier[draft_range.id].has_upcoming_weapon_duty is True
    assert by_soldier[draft_range.id].has_upcoming_matching_range is False


def test_excludes_soldier_who_cannot_qualify_for_any_weapon_duty_type(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="Root")
    structurally_ineligible = _duty_type(
        app_session, name="Restricted weapon duty", required_range_type=RangeType.laser
    )
    structurally_ineligible.requirements = {"allowed_genders": ["female"]}
    visible = create_soldier(app_session, personal_number="inq-eligible", hierarchy_node_id=node.id)
    excluded = create_soldier(app_session, personal_number="inq-no-weapon-duty", hierarchy_node_id=node.id)
    visible.gender = "female"
    excluded.gender = "male"
    _duty(app_session, soldier_id=excluded.id, duty_type=structurally_ineligible, start_date=AS_OF)
    app_session.commit()

    records = list_ineligible_soldiers(app_session, roots={node.id}, as_of=AS_OF)

    assert {record.soldier_id for record in records} == {visible.id}


def test_cancelled_matching_range_alone_does_not_cover_a_future_weapon_duty(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="branch", name="Root")
    laser_duty = _duty_type(app_session, name="Laser duty", required_range_type=RangeType.laser)
    soldier = create_soldier(app_session, personal_number="inq-301", hierarchy_node_id=node.id)
    _duty(app_session, soldier_id=soldier.id, duty_type=laser_duty, start_date=AS_OF)
    _range_assignment(
        app_session,
        soldier_id=soldier.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF,
        status=RangeEventStatus.cancelled,
    )
    app_session.commit()

    record = list_ineligible_soldiers(app_session, roots={node.id}, as_of=AS_OF)[0]

    assert record.soldier_id == soldier.id
    assert record.has_upcoming_weapon_duty is True
    assert record.has_upcoming_matching_range is False
    assert record.upcoming_matching_ranges == ()


def test_partial_matching_range_does_not_cover_every_future_weapon_duty(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="branch", name="Root")
    laser_duty = _duty_type(app_session, name="Laser duty", required_range_type=RangeType.laser)
    live_duty = _duty_type(app_session, name="Live duty", required_range_type=RangeType.live)
    soldier = create_soldier(app_session, personal_number="inq-302", hierarchy_node_id=node.id)
    _duty(app_session, soldier_id=soldier.id, duty_type=laser_duty, start_date=AS_OF)
    _duty(
        app_session,
        soldier_id=soldier.id,
        duty_type=live_duty,
        start_date=AS_OF + timedelta(days=1),
    )
    _range_assignment(
        app_session,
        soldier_id=soldier.id,
        node_id=node.id,
        range_type=RangeType.laser,
        event_date=AS_OF,
    )
    app_session.commit()

    record = list_ineligible_soldiers(app_session, roots={node.id}, as_of=AS_OF)[0]

    assert record.has_upcoming_weapon_duty is True
    assert record.has_upcoming_matching_range is False


def test_batches_related_records_for_all_scoped_soldiers(app_session: Session) -> None:
    root = create_node(app_session, level="branch", name="Root")
    soldiers = [
        create_soldier(app_session, personal_number=f"inq-batch-{index}", hierarchy_node_id=root.id)
        for index in range(5)
    ]
    select_count = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(app_session.bind, "before_cursor_execute", count_selects)
    try:
        records = list_ineligible_soldiers(app_session, roots={root.id}, as_of=AS_OF)
    finally:
        event.remove(app_session.bind, "before_cursor_execute", count_selects)

    assert {record.soldier_id for record in records} == {soldier.id for soldier in soldiers}
    assert select_count <= 4
