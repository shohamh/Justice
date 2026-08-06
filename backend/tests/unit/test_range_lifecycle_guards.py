from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.db.models import RangeAssignment, RangeEventStatus, RangeType
from app.services.ranges import (
    RangeValidationError,
    cancel_range_event,
    create_range_event,
    delete_range_event,
    update_range_event,
)
from tests.helpers import create_node, create_range_location, create_soldier


def _event(session: Session):
    node = create_node(session, level="?????", name="???????-?????-2")
    return create_range_event(
        session,
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        event_date=date(2026, 9, 10),
        range_location_id=create_range_location(session, name="????").id,
        required_count=2,
    )


def test_update_planned_event_edits_every_planning_field(app_session: Session) -> None:
    event = _event(app_session)
    new_node = create_node(app_session, level="?????", name="???????-?????-2-???")
    new_location = create_range_location(app_session, name="????")

    updated = update_range_event(
        app_session,
        event=event,
        hierarchy_node_id=new_node.id,
        range_type=RangeType.live,
        event_date=date(2026, 9, 11),
        start_time="08:00",
        end_time="12:00",
        range_location_id=new_location.id,
        required_count=3,
        reserve_count=1,
        arrival_instructions="????? ??????",
        contact_name="???? ?????",
        contact_phone="050-1234567",
        notes="?????",
    )

    assert (updated.hierarchy_node_id, updated.range_type, updated.date) == (
        new_node.id,
        RangeType.live,
        date(2026, 9, 11),
    )
    assert (updated.start_time, updated.end_time) == ("08:00", "12:00")
    assert (updated.range_location_id, updated.required_count, updated.reserve_count) == (new_location.id, 3, 1)
    assert updated.arrival_instructions == "????? ??????"


def test_update_planned_event_can_clear_nullable_fields(app_session: Session) -> None:
    event = _event(app_session)
    update_range_event(
        app_session,
        event=event,
        start_time="08:00",
        end_time="12:00",
        arrival_instructions="?????",
    )

    updated = update_range_event(
        app_session,
        event=event,
        start_time=None,
        end_time=None,
        arrival_instructions=None,
    )

    assert updated.start_time is None
    assert updated.end_time is None
    assert updated.arrival_instructions is None


def test_cancel_requires_and_persists_reason(app_session: Session) -> None:
    event = _event(app_session)

    with pytest.raises(RangeValidationError, match="reason_required"):
        cancel_range_event(app_session, event=event, reason="  ")

    cancelled = cancel_range_event(app_session, event=event, reason="??? ????")

    assert cancelled.status == RangeEventStatus.cancelled
    assert cancelled.cancellation_reason == "??? ????"


@pytest.mark.parametrize("status", [RangeEventStatus.completed, RangeEventStatus.cancelled])
def test_completed_and_cancelled_events_are_immutable(
    app_session: Session, status: RangeEventStatus
) -> None:
    event = _event(app_session)
    event.status = status
    app_session.commit()

    with pytest.raises(RangeValidationError, match="event_not_planned"):
        update_range_event(app_session, event=event, range_location_id=create_range_location(app_session, name="????").id)
    with pytest.raises(RangeValidationError, match="event_not_planned"):
        cancel_range_event(app_session, event=event, reason="????")
    with pytest.raises(RangeValidationError, match="event_not_planned"):
        delete_range_event(app_session, event=event)


def test_physical_delete_requires_empty_planned_event(app_session: Session) -> None:
    event = _event(app_session)
    node_id = event.hierarchy_node_id
    soldier = create_soldier(app_session, personal_number="9900001", hierarchy_node_id=node_id)
    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id)
    app_session.add(assignment)
    app_session.commit()

    with pytest.raises(RangeValidationError, match="event_has_assignments"):
        delete_range_event(app_session, event=event)

