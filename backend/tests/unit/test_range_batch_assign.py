from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeAssignment, RangeType, SoldierRangeQualification
from app.services.ranges import RangeValidationError, assign_batch, create_range_event
from tests.helpers import create_node, create_range_location, create_soldier


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
