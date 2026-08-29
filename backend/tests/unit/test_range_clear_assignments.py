from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeAssignment, RangeType
from app.services.ranges import RangeValidationError, assign_batch, clear_range_assignments, create_range_event
from tests.helpers import create_node, create_range_location, create_soldier


def _event(session: Session, *, required_count: int = 3, reserve_count: int = 1):
    node = create_node(session, level="branch", name="clear-scratch")
    session.add(DutyType(name="weapon clear-scratch", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(session, name="range").id,
        required_count=required_count, reserve_count=reserve_count,
    )
    return node, event


def test_clear_removes_everything_in_one_call(app_session: Session) -> None:
    node, event = _event(app_session)
    s1 = create_soldier(app_session, personal_number="clear-1", hierarchy_node_id=node.id)
    s2 = create_soldier(app_session, personal_number="clear-2", hierarchy_node_id=node.id)
    s3 = create_soldier(app_session, personal_number="clear-3", hierarchy_node_id=node.id)
    assign_batch(app_session, event=event, primary_soldier_ids=[s1.id, s2.id], reserve_soldier_ids=[s3.id], actor_id=None)

    cleared = clear_range_assignments(app_session, event=event, reason="test cleanup", actor_id=None)

    assert cleared == 3
    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    assert remaining == []


def test_clear_noop_when_nothing_assigned(app_session: Session) -> None:
    node, event = _event(app_session)
    assert clear_range_assignments(app_session, event=event, reason="test cleanup", actor_id=None) == 0


def test_clear_rejects_when_event_not_planned(app_session: Session) -> None:
    node, event = _event(app_session)
    event.status = "completed"
    app_session.flush()
    with pytest.raises(RangeValidationError):
        clear_range_assignments(app_session, event=event, reason="test cleanup", actor_id=None)
