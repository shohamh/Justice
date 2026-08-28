from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    DutyType,
    Notification,
    NotificationType,
    PersonalConstraint,
    PersonalConstraintOverride,
    RangeAssignment,
    RangeEventStatus,
    RangeType,
)
from app.services.ranges import (
    RangeValidationError,
    _validity_days,
    add_range_assignment,
    assign_batch,
    cancel_range_event,
    create_range_event,
    remove_range_assignment,
    update_range_event,
)
from app.services.settings_loader import set_setting
from tests.helpers import create_node, create_range_location, create_soldier


def _approved_constraint(session: Session, soldier_id, event_date: date) -> PersonalConstraint:
    c = PersonalConstraint(
        soldier_id=soldier_id, start_date=event_date, end_date=event_date, reason="r", status="approved",
    )
    session.add(c)
    session.flush()
    return c


def test_create_range_event_success(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א")

    event = create_range_event(
        app_session,
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        event_date=date(2026, 8, 20),
        range_location_id=create_range_location(app_session, name="מטווח דרום").id,
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
            range_location_id=create_range_location(app_session, name="מטווח").id,
            required_count=2,
        )


def test_create_range_event_rejects_unknown_location(app_session: Session) -> None:
    import uuid

    node = create_node(app_session, level="פלוגה", name="פלוגה מיקום-לא-קיים")

    with pytest.raises(RangeValidationError, match="range_location_not_found"):
        create_range_event(
            app_session,
            hierarchy_node_id=node.id,
            range_type=RangeType.live,
            event_date=date(2026, 8, 20),
            range_location_id=uuid.uuid4(),
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
            range_location_id=create_range_location(app_session, name="מטווח").id,
            required_count=-1,
        )


def test_update_range_event_changes_fields(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ג")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח ישן").id, required_count=3,
    )

    new_location = create_range_location(app_session, name="מטווח חדש")
    updated = update_range_event(app_session, event=event, range_location_id=new_location.id, required_count=5)

    assert updated.range_location_id == new_location.id
    assert updated.required_count == 5


def test_update_range_event_rejects_unknown_location(app_session: Session) -> None:
    import uuid

    node = create_node(app_session, level="פלוגה", name="פלוגה עדכון-מיקום-לא-קיים")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח ישן").id, required_count=3,
    )

    with pytest.raises(RangeValidationError, match="range_location_not_found"):
        update_range_event(app_session, event=event, range_location_id=uuid.uuid4())


def test_update_range_event_writes_audit_entry(app_session: Session) -> None:
    import uuid

    node = create_node(app_session, level="פלוגה", name="פלוגה עדכון-ביקורת")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח ישן").id, required_count=3,
    )
    actor_id = uuid.uuid4()
    old_location_id = event.range_location_id
    new_location = create_range_location(app_session, name="מטווח חדש")

    update_range_event(app_session, event=event, range_location_id=new_location.id, actor_id=actor_id)

    entry = app_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "range_event",
            AuditLog.entity_id == event.id,
            AuditLog.action == "range_event.update",
        )
    ).scalar_one()
    assert entry.actor_id == actor_id
    assert entry.before.get("range_location_id") == str(old_location_id)
    assert entry.after.get("range_location_id") == str(new_location.id)


def test_cancel_range_event_sets_status(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ד")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=2,
    )

    cancelled = cancel_range_event(app_session, event=event, reason="weather")

    assert cancelled.status == RangeEventStatus.cancelled


def test_cancel_range_event_writes_audit_entry(app_session: Session) -> None:
    import uuid

    node = create_node(app_session, level="פלוגה", name="פלוגה ביטול-ביקורת")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=2,
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
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=2,
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
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=3,
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
            Notification.reference_type == "range_event",
            Notification.reference_id == event.id,
        )
    ).scalar_one_or_none()
    assert notification is not None
    assert notification.body == "מטווח לייזר · 20.08.2026"


def test_add_range_assignment_rejects_soldier_outside_subunit(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ו")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ז")
    soldier = create_soldier(app_session, personal_number="4000002", hierarchy_node_id=other_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=3,
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
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=3,
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
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח א").id, required_count=1,
    )
    second_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, range_location_id=create_range_location(app_session, name="מטווח ב").id, required_count=1,
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
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=3,
    )
    weapon_duty = DutyType(name="שמירה עם נשק ט", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    assignment_id = assignment.id

    remove_range_assignment(app_session, assignment=assignment, reason="test removal")

    assert app_session.get(RangeAssignment, assignment_id) is None


def test_roster_change_notifies_existing_and_removed_assignees(app_session: Session) -> None:
    node = create_node(app_session, level="×¤×œ×•×’×”", name="×¤×œ×•×’×” ×¨×•×¡×˜×¨")
    first = create_soldier(app_session, personal_number="4900001", hierarchy_node_id=node.id)
    second = create_soldier(app_session, personal_number="4900002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="×ž×˜×•×•×—").id, required_count=2,
    )
    weapon_duty = DutyType(
        name="×©×ž×™×¨×” ×¢× × ×©×§ ×¨×•×¡×˜×¨", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    add_range_assignment(app_session, event=event, soldier_id=first.id, is_reserve=False)
    second_assignment = add_range_assignment(
        app_session, event=event, soldier_id=second.id, is_reserve=False,
    )
    assert app_session.execute(select(Notification).where(
        Notification.soldier_id == first.id,
        Notification.type == NotificationType.range_roster_changed,
        Notification.reference_id == event.id,
    )).scalars().first() is not None

    remove_range_assignment(app_session, assignment=second_assignment, reason="test removal")
    assert app_session.execute(select(Notification).where(
        Notification.soldier_id == second.id,
        Notification.type == NotificationType.range_roster_changed,
        Notification.reference_id == event.id,
    )).scalars().first() is not None


def test_cancellation_notifies_assignees_with_reason_and_event_reference(app_session: Session) -> None:
    node = create_node(app_session, level="×¤×œ×•×’×”", name="×¤×œ×•×’×” ×‘×™×˜×•×œ")
    soldier = create_soldier(app_session, personal_number="4900003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="×ž×˜×•×•×— ×¦×¤×•× ×™").id, required_count=1,
    )
    weapon_duty = DutyType(
        name="×©×ž×™×¨×” ×¢× × ×©×§ ×‘×™×˜×•×œ", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    cancel_range_event(app_session, event=event, reason="weather")

    notification = app_session.execute(select(Notification).where(
        Notification.soldier_id == soldier.id,
        Notification.type == NotificationType.range_cancelled,
        Notification.reference_type == "range_event",
        Notification.reference_id == event.id,
    )).scalar_one()
    assert "weather" in (notification.body or "")


def test_add_range_assignment_rejects_when_event_not_planned(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה תת-הוספה-לא-מתוכנן")
    soldier = create_soldier(app_session, personal_number="4000006", hierarchy_node_id=node.id)
    weapon_duty = DutyType(name="שמירה עם נשק תת-הוספה-לא-מתוכנן", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=3,
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
        event_date=date(2026, 8, 20), range_location_id=create_range_location(app_session, name="מטווח").id, required_count=3,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    cancel_range_event(app_session, event=event, reason="cancelled")

    with pytest.raises(RangeValidationError):
        remove_range_assignment(app_session, assignment=assignment, reason="test removal")


def test_remove_range_assignment_requires_reason(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="rra-node-1")
    soldier = create_soldier(app_session, personal_number="rra-001", hierarchy_node_id=node.id)
    weapon_duty = DutyType(name="שמירה עם נשק rra-1", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    with pytest.raises(TypeError):
        remove_range_assignment(app_session, assignment=assignment, actor_id=soldier.id)  # type: ignore[call-arg]


def test_remove_range_assignment_writes_audit_log(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="rra-node-2")
    soldier = create_soldier(app_session, personal_number="rra-002", hierarchy_node_id=node.id)
    manager = create_soldier(app_session, personal_number="rra-003", role="duty_manager", hierarchy_node_id=node.id)
    weapon_duty = DutyType(name="שמירה עם נשק rra-2", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    assignment_id = assignment.id

    remove_range_assignment(app_session, assignment=assignment, reason="חייל שוחרר מהיחידה", actor_id=manager.id)

    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.id == assignment_id)
    ).scalar_one_or_none()
    assert remaining is None

    audit = app_session.execute(
        select(AuditLog).where(
            AuditLog.action == "range_assignment.remove",
            AuditLog.entity_id == assignment_id,
        )
    ).scalar_one()
    assert audit.before["soldier_id"] == str(soldier.id)
    assert audit.before["range_event_id"] == str(event.id)
    assert audit.context["reason"] == "חייל שוחרר מהיחידה"
    assert audit.actor_id == manager.id


def test_range_assignment_blocked_when_setting_off(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="pco-node-1")
    soldier = create_soldier(app_session, personal_number="pco-001", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="שמירה עם נשק pco-1", score_per_day=Decimal("1.00"),
                              requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    _approved_constraint(app_session, soldier.id, event.date)
    set_setting(app_session, "constraints.allow_manual_override", False, actor_id=None)

    with pytest.raises(RangeValidationError, match="personal_constraint_blocked"):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_range_assignment_requires_reason(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="pco-node-2")
    soldier = create_soldier(app_session, personal_number="pco-002", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="שמירה עם נשק pco-2", score_per_day=Decimal("1.00"),
                              requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    _approved_constraint(app_session, soldier.id, event.date)

    with pytest.raises(RangeValidationError, match="override_reason_required"):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_range_assignment_succeeds_with_reason(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="pco-node-3")
    soldier = create_soldier(app_session, personal_number="pco-003", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="שמירה עם נשק pco-3", score_per_day=Decimal("1.00"),
                              requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    constraint = _approved_constraint(app_session, soldier.id, event.date)

    assignment = add_range_assignment(
        app_session, event=event, soldier_id=soldier.id, is_reserve=False,
        override_reason="צורך מבצעי",
    )

    override = app_session.query(PersonalConstraintOverride).filter(
        PersonalConstraintOverride.personal_constraint_id == constraint.id,
    ).one()
    assert override.reference_id == assignment.id
    assert override.assignment_kind == "range"
    assert override.soldier_id == soldier.id
    assert override.reason == "צורך מבצעי"


def test_range_assignment_without_constraint_unaffected(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="pco-node-4")
    soldier = create_soldier(app_session, personal_number="pco-004", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="שמירה עם נשק pco-4", score_per_day=Decimal("1.00"),
                              requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )

    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    assert assignment.id is not None
    assert app_session.query(PersonalConstraintOverride).filter(
        PersonalConstraintOverride.soldier_id == soldier.id,
    ).first() is None


def test_range_batch_assign_requires_reason_and_writes_override(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="pco-node-5")
    blocked_soldier = create_soldier(app_session, personal_number="pco-005", hierarchy_node_id=node.id)
    free_soldier = create_soldier(app_session, personal_number="pco-006", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="שמירה עם נשק pco-5", score_per_day=Decimal("1.00"),
                              requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=2,
    )
    constraint = _approved_constraint(app_session, blocked_soldier.id, event.date)

    with pytest.raises(RangeValidationError, match="override_reason_required"):
        assign_batch(
            app_session, event=event,
            primary_soldier_ids=[blocked_soldier.id, free_soldier.id], reserve_soldier_ids=[],
        )

    rows = assign_batch(
        app_session, event=event,
        primary_soldier_ids=[blocked_soldier.id, free_soldier.id], reserve_soldier_ids=[],
        override_reason="צורך מבצעי",
    )

    assert len(rows) == 2
    override = app_session.query(PersonalConstraintOverride).filter(
        PersonalConstraintOverride.personal_constraint_id == constraint.id,
    ).one()
    blocked_row = next(r for r in rows if r.soldier_id == blocked_soldier.id)
    assert override.reference_id == blocked_row.id
    assert override.assignment_kind == "range"
    # The soldier without a constraint gets no override row at all.
    assert app_session.query(PersonalConstraintOverride).filter(
        PersonalConstraintOverride.soldier_id == free_soldier.id,
    ).first() is None
