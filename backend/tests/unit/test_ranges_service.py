from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    DutyType,
    Notification,
    NotificationType,
    RangeAssignment,
    RangeEventStatus,
    RangeType,
)
from app.services.ranges import (
    RangeValidationError,
    _validity_days,
    add_range_assignment,
    cancel_range_event,
    create_range_event,
    remove_range_assignment,
    update_range_event,
)
from tests.helpers import create_node, create_soldier


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


def test_update_range_event_writes_audit_entry(app_session: Session) -> None:
    import uuid

    node = create_node(app_session, level="פלוגה", name="פלוגה עדכון-ביקורת")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date(2026, 8, 20), location="מטווח ישן", required_count=3,
    )
    actor_id = uuid.uuid4()

    update_range_event(app_session, event=event, location="מטווח חדש", actor_id=actor_id)

    entry = app_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "range_event",
            AuditLog.entity_id == event.id,
            AuditLog.action == "range_event.update",
        )
    ).scalar_one()
    assert entry.actor_id == actor_id
    assert entry.before.get("location") == "מטווח ישן"
    assert entry.after.get("location") == "מטווח חדש"


def test_cancel_range_event_sets_status(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ד")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=2,
    )

    cancelled = cancel_range_event(app_session, event=event, reason="weather")

    assert cancelled.status == RangeEventStatus.cancelled


def test_cancel_range_event_writes_audit_entry(app_session: Session) -> None:
    import uuid

    node = create_node(app_session, level="פלוגה", name="פלוגה ביטול-ביקורת")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=2,
    )
    actor_id = uuid.uuid4()

    cancel_range_event(app_session, event=event, actor_id=actor_id, reason="weather")

    entry = app_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "range_event",
            AuditLog.entity_id == event.id,
            AuditLog.action == "range_event.cancel",
        )
    ).scalar_one()
    assert entry.actor_id == actor_id
    assert entry.before == {"status": "planned"}
    assert entry.after == {"status": "cancelled"}


def test_cancel_range_event_rejects_already_cancelled_event(app_session: Session) -> None:
    """Cancelling an already-cancelled event must record the real prior status in
    the audit trail, not a hardcoded "planned" - otherwise the audit falsely
    claims the event transitioned from planned when it was already cancelled."""
    node = create_node(app_session, level="פלוגה", name="פלוגה ביטול-כפול")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=2,
    )

    cancel_range_event(app_session, event=event, reason="weather")
    with pytest.raises(RangeValidationError, match="event_not_planned"):
        cancel_range_event(app_session, event=event, reason="weather")

    entries = app_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "range_event",
            AuditLog.entity_id == event.id,
            AuditLog.action == "range_event.cancel",
        ).order_by(AuditLog.created_at)
    ).scalars().all()
    assert len(entries) == 1
    assert entries[0].before == {"status": "planned"}


def test_validity_days_falls_back_to_365_for_live_and_alal(app_session: Session) -> None:
    """No mitvachim.*_validity_days setting is seeded in the test DB (unlike the
    real migration), so calling _validity_days directly exercises the
    SettingNotFound fallback path."""
    assert _validity_days(app_session, RangeType.laser) == 180
    assert _validity_days(app_session, RangeType.live) == 365
    assert _validity_days(app_session, RangeType.alal) == 365


def test_add_range_assignment_success(app_session: Session) -> None:
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
    notification = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.type == NotificationType.range_assignment_confirmed,
            Notification.reference_type == "range_assignment",
            Notification.reference_id == assignment.id,
        )
    ).scalar_one_or_none()
    assert notification is not None


def test_add_range_assignment_rejects_soldier_outside_subunit(app_session: Session) -> None:
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
    node = create_node(app_session, level="פלוגה", name="פלוגה ח")
    soldier = create_soldier(app_session, personal_number="4000003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    # No requires_weapon=True duty type is eligible for this node -> structurally exempt.

    with pytest.raises(RangeValidationError):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_add_range_assignment_rejects_soldier_booked_at_another_range_same_day(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה שיבוץ-כפול-מטווח")
    soldier = create_soldier(app_session, personal_number="4000007", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק שיבוץ-כפול-מטווח",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()
    event_date = date(2026, 8, 20)
    first_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח א", required_count=1,
    )
    second_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, location="מטווח ב", required_count=1,
    )
    add_range_assignment(
        app_session, event=first_event, soldier_id=soldier.id, is_reserve=False
    )

    with pytest.raises(RangeValidationError, match="soldier_already_assigned_on_date"):
        add_range_assignment(
            app_session, event=second_event, soldier_id=soldier.id, is_reserve=False
        )


def test_remove_range_assignment_deletes_row(app_session: Session) -> None:
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
    cancel_range_event(app_session, event=event, reason="cancelled")

    with pytest.raises(RangeValidationError):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_remove_range_assignment_rejects_when_event_not_planned(app_session: Session) -> None:
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
    cancel_range_event(app_session, event=event, reason="cancelled")

    with pytest.raises(RangeValidationError):
        remove_range_assignment(app_session, assignment=assignment)
