from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyManagerScope,
    DutyType,
    RangeAssignment,
    RangeType,
    Soldier,
    SoldierRangeQualification,
)
from app.services.ranges import RangeValidationError, assign_batch, create_range_event
from tests.helpers import create_node, create_range_location, create_soldier


def _dm_for(session: Session, node, *, personal_number: str) -> Soldier:
    dm = create_soldier(session, personal_number=personal_number, role="duty_manager", hierarchy_node_id=None)
    session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    session.commit()
    return dm


def _event(session: Session, *, required_count: int = 2, reserve_count: int = 1):
    node = create_node(session, level="branch", name="batch-assign")
    session.add(DutyType(name="weapon batch-assign", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(session, name="range").id,
        required_count=required_count, reserve_count=reserve_count,
    )
    return node, event


def test_creates_all_assignments_as_non_draft(app_session: Session) -> None:
    node, event = _event(app_session)
    primary = create_soldier(app_session, personal_number="batch-primary", hierarchy_node_id=node.id)
    reserve = create_soldier(app_session, personal_number="batch-reserve", hierarchy_node_id=node.id)

    created = assign_batch(app_session, event=event, primary_soldier_ids=[primary.id], reserve_soldier_ids=[reserve.id], actor_id=None)

    assert len(created) == 2
    assert all(not a.is_draft for a in created)
    primary_rows = [a for a in created if not a.is_reserve]
    reserve_rows = [a for a in created if a.is_reserve]
    assert [a.soldier_id for a in primary_rows] == [primary.id]
    assert [a.soldier_id for a in reserve_rows] == [reserve.id]


def test_rejects_the_whole_batch_if_one_soldier_is_invalid(app_session: Session) -> None:
    node, event = _event(app_session)
    valid = create_soldier(app_session, personal_number="batch-valid", hierarchy_node_id=node.id)
    other_node = create_node(app_session, level="branch", name="batch-outside")
    outside = create_soldier(app_session, personal_number="batch-outside", hierarchy_node_id=other_node.id)

    with pytest.raises(RangeValidationError):
        assign_batch(app_session, event=event, primary_soldier_ids=[valid.id, outside.id], reserve_soldier_ids=[], actor_id=None)

    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    assert remaining == []


def test_records_the_real_assignment_reason_not_manual(app_session: Session) -> None:
    node, event = _event(app_session)
    qualified = create_soldier(app_session, personal_number="batch-qualified", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=qualified.id, range_type=RangeType.laser,
        valid_until=date.today() + timedelta(days=30),
    ))
    app_session.flush()

    created = assign_batch(app_session, event=event, primary_soldier_ids=[qualified.id], reserve_soldier_ids=[], actor_id=None)

    assert len(created) == 1
    assert created[0].assignment_reason_code == "qualified"
    assert created[0].assignment_reason_code != "manual"


def test_rejects_a_primary_batch_that_would_exceed_required_count(app_session: Session) -> None:
    node, event = _event(app_session, required_count=1, reserve_count=0)
    already = create_soldier(app_session, personal_number="batch-cap-existing", hierarchy_node_id=node.id)
    assign_batch(app_session, event=event, primary_soldier_ids=[already.id], reserve_soldier_ids=[], actor_id=None)
    extra = create_soldier(app_session, personal_number="batch-cap-extra", hierarchy_node_id=node.id)

    with pytest.raises(RangeValidationError, match="primary_capacity_exceeded"):
        assign_batch(app_session, event=event, primary_soldier_ids=[extra.id], reserve_soldier_ids=[], actor_id=None)

    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id, RangeAssignment.soldier_id == extra.id)
    ).scalars().all()
    assert remaining == []


def test_rejects_a_reserve_batch_that_would_exceed_reserve_count(app_session: Session) -> None:
    node, event = _event(app_session, required_count=1, reserve_count=1)
    already = create_soldier(app_session, personal_number="batch-cap-reserve-existing", hierarchy_node_id=node.id)
    assign_batch(app_session, event=event, primary_soldier_ids=[], reserve_soldier_ids=[already.id], actor_id=None)
    extra = create_soldier(app_session, personal_number="batch-cap-reserve-extra", hierarchy_node_id=node.id)

    with pytest.raises(RangeValidationError, match="reserve_capacity_exceeded"):
        assign_batch(app_session, event=event, primary_soldier_ids=[], reserve_soldier_ids=[extra.id], actor_id=None)


def test_accepts_a_soldier_from_a_sibling_node_within_the_managers_scope(app_session: Session) -> None:
    """Regression test: the candidate panel offers reserves from anywhere in the
    requesting manager's scope, not just the event's own sub-unit (see
    range_auto_assign._soldier_pool). Saving that selection must actually succeed —
    previously assign_batch/_validate_and_build_assignment still hard-rejected
    anyone outside the event's exact hierarchy_node_id, so a manager picking a
    candidate the UI legitimately offered them got a generic save failure."""
    parent = create_node(app_session, level="גדוד", name="גדוד batch-sibling")
    event_node = create_node(app_session, level="פלוגה", name="פלוגה batch-sibling-host", parent=parent)
    sibling_node = create_node(app_session, level="פלוגה", name="פלוגה batch-sibling-guest", parent=parent)
    app_session.add(DutyType(name="weapon batch-sibling", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[parent.id]))
    app_session.flush()
    dm = _dm_for(app_session, parent, personal_number="batch-sibling-dm")
    sibling_soldier = create_soldier(app_session, personal_number="batch-sibling-soldier", hierarchy_node_id=sibling_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=event_node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session, name="range-sibling").id,
        required_count=1, reserve_count=1,
    )

    created = assign_batch(
        app_session, event=event, primary_soldier_ids=[sibling_soldier.id], reserve_soldier_ids=[], actor_id=None, user=dm,
    )

    assert [a.soldier_id for a in created] == [sibling_soldier.id]


def test_still_rejects_a_soldier_outside_the_managers_scope_even_with_user_passed(app_session: Session) -> None:
    node, event = _event(app_session)
    dm = _dm_for(app_session, node, personal_number="batch-outside-scope-dm")
    other_node = create_node(app_session, level="branch", name="batch-outside-scope")
    outside = create_soldier(app_session, personal_number="batch-outside-scope-soldier", hierarchy_node_id=other_node.id)

    with pytest.raises(RangeValidationError, match="soldier_outside_event_subunit"):
        assign_batch(app_session, event=event, primary_soldier_ids=[outside.id], reserve_soldier_ids=[], actor_id=None, user=dm)


def test_rejects_a_batch_of_multiple_primaries_that_alone_exceeds_capacity(app_session: Session) -> None:
    node, event = _event(app_session, required_count=1, reserve_count=0)
    first = create_soldier(app_session, personal_number="batch-cap-multi-1", hierarchy_node_id=node.id)
    second = create_soldier(app_session, personal_number="batch-cap-multi-2", hierarchy_node_id=node.id)

    with pytest.raises(RangeValidationError, match="primary_capacity_exceeded"):
        assign_batch(app_session, event=event, primary_soldier_ids=[first.id, second.id], reserve_soldier_ids=[], actor_id=None)

    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    assert remaining == []
