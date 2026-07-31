from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.db.models import RangeEventStatus, RangeType
from app.services.ranges import (
    RangeValidationError,
    cancel_range_event,
    create_range_event,
    update_range_event,
)
from tests.helpers import create_node


def test_create_range_event_success(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א")

    event = create_range_event(
        app_session,
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        event_date=date(2026, 8, 20),
        location="מטווח דרום",
        required_count=4,
        reserve_count=1,
    )

    assert event.id is not None
    assert event.status == RangeEventStatus.planned


def test_create_range_event_rejects_unknown_node(app_session: Session) -> None:
    import uuid

    with pytest.raises(RangeValidationError):
        create_range_event(
            app_session,
            hierarchy_node_id=uuid.uuid4(),
            range_type=RangeType.live,
            event_date=date(2026, 8, 20),
            location="מטווח",
            required_count=2,
        )


def test_create_range_event_rejects_negative_counts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ב")

    with pytest.raises(RangeValidationError):
        create_range_event(
            app_session,
            hierarchy_node_id=node.id,
            range_type=RangeType.alal,
            event_date=date(2026, 8, 20),
            location="מטווח",
            required_count=-1,
        )


def test_update_range_event_changes_fields(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ג")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date(2026, 8, 20), location="מטווח ישן", required_count=3,
    )

    updated = update_range_event(app_session, event=event, location="מטווח חדש", required_count=5)

    assert updated.location == "מטווח חדש"
    assert updated.required_count == 5


def test_cancel_range_event_sets_status(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ד")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=2,
    )

    cancelled = cancel_range_event(app_session, event=event)

    assert cancelled.status == RangeEventStatus.cancelled
