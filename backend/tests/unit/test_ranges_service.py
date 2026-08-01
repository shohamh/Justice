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


from app.db.models import RangeAssignment
from app.services.ranges import add_range_assignment, remove_range_assignment
from tests.helpers import create_soldier


def test_add_range_assignment_success(app_session: Session) -> None:
    from app.db.models import DutyType
    from decimal import Decimal

    node = create_node(app_session, level="פלוגה", name="פלוגה ה")
    soldier = create_soldier(app_session, personal_number="4000001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    weapon_duty = DutyType(name="שמירה עם נשק א", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()

    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    assert assignment.range_event_id == event.id
    assert assignment.is_reserve is False


def test_add_range_assignment_rejects_soldier_outside_subunit(app_session: Session) -> None:
    from app.db.models import DutyType
    from decimal import Decimal

    node = create_node(app_session, level="פלוגה", name="פלוגה ו")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ז")
    soldier = create_soldier(app_session, personal_number="4000002", hierarchy_node_id=other_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    weapon_duty = DutyType(name="שמירה עם נשק ו", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[other_node.id])
    app_session.add(weapon_duty)
    app_session.flush()

    with pytest.raises(RangeValidationError):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_add_range_assignment_rejects_exempt_soldier(app_session: Session) -> None:
    from app.db.models import DutyType

    node = create_node(app_session, level="פלוגה", name="פלוגה ח")
    soldier = create_soldier(app_session, personal_number="4000003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    # No requires_weapon=True duty type is eligible for this node -> structurally exempt.

    with pytest.raises(RangeValidationError):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_remove_range_assignment_deletes_row(app_session: Session) -> None:
    from app.db.models import DutyType
    from decimal import Decimal

    node = create_node(app_session, level="פלוגה", name="פלוגה ט")
    soldier = create_soldier(app_session, personal_number="4000004", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    weapon_duty = DutyType(name="שמירה עם נשק ט", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    assignment_id = assignment.id

    remove_range_assignment(app_session, assignment=assignment)

    assert app_session.get(RangeAssignment, assignment_id) is None


def test_add_range_assignment_rejects_when_event_not_planned(app_session: Session) -> None:
    from app.db.models import DutyType
    from decimal import Decimal

    node = create_node(app_session, level="פלוגה", name="פלוגה תת-הוספה-לא-מתוכנן")
    soldier = create_soldier(app_session, personal_number="4000006", hierarchy_node_id=node.id)
    weapon_duty = DutyType(name="שמירה עם נשק תת-הוספה-לא-מתוכנן", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    cancel_range_event(app_session, event=event)

    with pytest.raises(RangeValidationError):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_remove_range_assignment_rejects_when_event_not_planned(app_session: Session) -> None:
    from app.db.models import DutyType
    from decimal import Decimal

    node = create_node(app_session, level="פלוגה", name="פלוגה תת-לא-מתוכנן")
    soldier = create_soldier(app_session, personal_number="4000005", hierarchy_node_id=node.id)
    weapon_duty = DutyType(name="שמירה עם נשק תת-לא-מתוכנן", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    cancel_range_event(app_session, event=event)

    with pytest.raises(RangeValidationError):
        remove_range_assignment(app_session, assignment=assignment)
