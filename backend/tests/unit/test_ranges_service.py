from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    DutyAssignment,
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
from tests.helpers import create_duty_location, create_node, create_range_location, create_soldier


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


def test_remove_range_assignment_rejects_when_event_already_happened(app_session: Session) -> None:
    node = create_node(app_session, level="×¤×œ×•×’×”", name="past-range-clear")
    soldier = create_soldier(app_session, personal_number="past-range-clear", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() - timedelta(days=1),
        range_location_id=create_range_location(app_session, name="past range").id, required_count=1,
    )
    assignment = RangeAssignment(
        range_event_id=event.id, soldier_id=soldier.id, is_reserve=False,
    )
    app_session.add(assignment)
    app_session.commit()

    with pytest.raises(RangeValidationError, match="event_already_happened"):
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


def test_reconciliation_removes_later_primary_and_reserve_in_event_date_order(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="reconciliation ordering")
    soldier = create_soldier(app_session, personal_number="reconciliation-001", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="reconciliation ordering weapon", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    location = create_range_location(app_session, name="reconciliation ordering range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later_reserve_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=15), range_location_id=location.id, required_count=0,
        reserve_count=1,
    )
    later_primary_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    add_range_assignment(app_session, event=source_event, soldier_id=soldier.id, is_reserve=False)
    # The day-10 primary is created before the day-15 reserve: creating it afterwards
    # would reconcile the reserve away itself, leaving nothing for the explicit call
    # below (which is what this test is about) to remove.
    later_primary = add_range_assignment(app_session, event=later_primary_event, soldier_id=soldier.id, is_reserve=False)
    later_reserve = add_range_assignment(app_session, event=later_reserve_event, soldier_id=soldier.id, is_reserve=True)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=soldier.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == [later_primary.id, later_reserve.id]
    assert app_session.get(RangeAssignment, later_primary.id) is None
    assert app_session.get(RangeAssignment, later_reserve.id) is None


def test_reconciliation_keeps_draft_cancelled_and_completed_targets(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="reconciliation target states")
    soldier = create_soldier(app_session, personal_number="reconciliation-002", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="reconciliation target states weapon", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    location = create_range_location(app_session, name="reconciliation target states range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    draft_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    cancelled_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=15), range_location_id=location.id, required_count=1,
    )
    completed_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=20), range_location_id=location.id, required_count=1,
    )
    add_range_assignment(app_session, event=source_event, soldier_id=soldier.id, is_reserve=False)
    draft_target = RangeAssignment(range_event_id=draft_event.id, soldier_id=soldier.id, is_draft=True)
    cancelled_target = RangeAssignment(range_event_id=cancelled_event.id, soldier_id=soldier.id)
    completed_target = RangeAssignment(range_event_id=completed_event.id, soldier_id=soldier.id)
    cancelled_event.status = RangeEventStatus.cancelled
    completed_event.status = RangeEventStatus.completed
    app_session.add_all([draft_target, cancelled_target, completed_target])
    app_session.commit()

    result = reconcile_future_range_assignments(
        app_session, soldier_id=soldier.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == []
    assert app_session.get(RangeAssignment, draft_target.id) is not None
    assert app_session.get(RangeAssignment, cancelled_target.id) is not None
    assert app_session.get(RangeAssignment, completed_target.id) is not None


def test_reconciliation_writes_removal_audit_without_committing(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="reconciliation transaction")
    manager = create_soldier(app_session, personal_number="reconciliation-003", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(app_session, personal_number="reconciliation-004", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="reconciliation transaction weapon", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    location = create_range_location(app_session, name="reconciliation transaction range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    target_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    add_range_assignment(app_session, event=source_event, soldier_id=soldier.id, is_reserve=False)
    target = add_range_assignment(app_session, event=target_event, soldier_id=soldier.id, is_reserve=False)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=soldier.id, source_event=source_event, actor_id=manager.id,
    )

    audit = app_session.execute(select(AuditLog).where(
        AuditLog.action == "range_assignment.remove", AuditLog.entity_id == target.id,
    )).scalar_one()
    assert result.removed_assignment_ids == [target.id]
    assert audit.before == {
        "soldier_id": str(soldier.id),
        "range_event_id": str(target_event.id),
        "is_reserve": False,
    }
    assert audit.actor_id == manager.id

    app_session.rollback()
    app_session.expire_all()

    assert app_session.get(RangeAssignment, target.id) is not None
    assert app_session.execute(select(AuditLog).where(AuditLog.entity_id == target.id)).scalar_one_or_none() is None


def _weapon_duty_type(session: Session, *, node, name: str) -> DutyType:
    duty_type = DutyType(
        name=name, score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id],
    )
    session.add(duty_type)
    session.flush()
    return duty_type


def test_reconciliation_refills_vacated_primary_slot(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="refill primary")
    _weapon_duty_type(app_session, node=node, name="refill primary weapon")
    covered = create_soldier(app_session, personal_number="refill-001", hierarchy_node_id=node.id)
    replacement = create_soldier(app_session, personal_number="refill-002", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="refill primary range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    add_range_assignment(app_session, event=source_event, soldier_id=covered.id, is_reserve=False)
    later = add_range_assignment(app_session, event=later_event, soldier_id=covered.id, is_reserve=False)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=covered.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == [later.id]
    assert result.unfilled_primary_count == 0
    assert len(result.refilled_primary_assignment_ids) == 1
    refilled = app_session.get(RangeAssignment, result.refilled_primary_assignment_ids[0])
    assert refilled.range_event_id == later_event.id
    assert refilled.is_reserve is False
    assert refilled.soldier_id == replacement.id


def test_reconciliation_refills_vacated_reserve_slot(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="refill reserve")
    _weapon_duty_type(app_session, node=node, name="refill reserve weapon")
    covered = create_soldier(app_session, personal_number="refill-003", hierarchy_node_id=node.id)
    replacement = create_soldier(app_session, personal_number="refill-004", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="refill reserve range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id,
        required_count=0, reserve_count=1,
    )
    add_range_assignment(app_session, event=source_event, soldier_id=covered.id, is_reserve=False)
    later = add_range_assignment(app_session, event=later_event, soldier_id=covered.id, is_reserve=True)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=covered.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == [later.id]
    assert result.refilled_primary_assignment_ids == []
    assert len(result.refilled_reserve_assignment_ids) == 1
    refilled = app_session.get(RangeAssignment, result.refilled_reserve_assignment_ids[0])
    assert refilled.range_event_id == later_event.id
    assert refilled.is_reserve is True
    assert refilled.soldier_id == replacement.id


def test_reconciliation_refill_never_crosses_primary_and_reserve_slots(app_session: Session) -> None:
    """The top-ranked candidate here ranks highly because of an upcoming *reserve*
    duty — that must still put them in the vacated PRIMARY slot, never in reserve."""
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="refill no cross-fill")
    weapon_duty_type = _weapon_duty_type(app_session, node=node, name="refill no cross-fill weapon")
    covered = create_soldier(app_session, personal_number="refill-005", hierarchy_node_id=node.id)
    reserve_ranked = create_soldier(app_session, personal_number="refill-006", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="refill-007", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="refill no cross-fill range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id,
        required_count=1, reserve_count=1,
    )
    duty_date = later_event.date + timedelta(days=2)
    app_session.add(DutyAssignment(
        soldier_id=reserve_ranked.id, duty_type_id=weapon_duty_type.id,
        duty_location_id=create_duty_location(app_session, name="refill no cross-fill duty").id,
        start_date=duty_date, end_date=duty_date, status="published", is_reserve=True,
    ))
    app_session.flush()
    add_range_assignment(app_session, event=source_event, soldier_id=covered.id, is_reserve=False)
    add_range_assignment(app_session, event=later_event, soldier_id=covered.id, is_reserve=False)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=covered.id, source_event=source_event, actor_id=None,
    )

    assert result.refilled_reserve_assignment_ids == []
    assert len(result.refilled_primary_assignment_ids) == 1
    refilled = app_session.get(RangeAssignment, result.refilled_primary_assignment_ids[0])
    assert refilled.soldier_id == reserve_ranked.id
    assert refilled.is_reserve is False
    assert app_session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == later_event.id, RangeAssignment.is_reserve.is_(True),
    )).scalars().all() == []


def test_reconciliation_records_shortage_when_no_replacement_exists(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="refill shortage")
    _weapon_duty_type(app_session, node=node, name="refill shortage weapon")
    covered = create_soldier(app_session, personal_number="refill-008", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="refill shortage range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    add_range_assignment(app_session, event=source_event, soldier_id=covered.id, is_reserve=False)
    later = add_range_assignment(app_session, event=later_event, soldier_id=covered.id, is_reserve=False)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=covered.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == [later.id]
    assert result.refilled_primary_assignment_ids == []
    assert result.unfilled_primary_count == 1
    assert result.unfilled_reserve_count == 0
    # The valid removal stands even though the slot could not be refilled.
    assert app_session.get(RangeAssignment, later.id) is None
    assert app_session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == later_event.id,
    )).scalars().all() == []


def test_reconciliation_refill_only_draws_from_event_subtree(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    parent = create_node(app_session, level="branch", name="refill scope parent")
    child = create_node(app_session, level="פלוגה", name="refill scope child", parent=parent)
    weapon_duty_type = _weapon_duty_type(app_session, node=parent, name="refill scope weapon")
    covered = create_soldier(app_session, personal_number="refill-009", hierarchy_node_id=child.id)
    in_subtree = create_soldier(app_session, personal_number="refill-010", hierarchy_node_id=child.id)
    outside_subtree = create_soldier(app_session, personal_number="refill-011", hierarchy_node_id=parent.id)
    location = create_range_location(app_session, name="refill scope range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=child.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=child.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    # The outsider would rank top of the pool (upcoming weapon duty) if the pool
    # were ever widened beyond the event's own subtree.
    duty_date = later_event.date + timedelta(days=2)
    app_session.add(DutyAssignment(
        soldier_id=outside_subtree.id, duty_type_id=weapon_duty_type.id,
        duty_location_id=create_duty_location(app_session, name="refill scope duty").id,
        start_date=duty_date, end_date=duty_date, status="published",
    ))
    app_session.flush()
    add_range_assignment(app_session, event=source_event, soldier_id=covered.id, is_reserve=False)
    add_range_assignment(app_session, event=later_event, soldier_id=covered.id, is_reserve=False)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=covered.id, source_event=source_event, actor_id=None,
    )

    assert len(result.refilled_primary_assignment_ids) == 1
    refilled = app_session.get(RangeAssignment, result.refilled_primary_assignment_ids[0])
    assert refilled.soldier_id == in_subtree.id
    assert refilled.soldier_id != outside_subtree.id


def _reconciliation_gap_fixture(app_session: Session, *, name: str, prefix: str, duty_offset_days: int):
    """Source and target both laser, so the target's validity window outlives the
    source's by exactly the 5 days between the two events. A weapon duty placed at
    `duty_offset_days` past the source event decides whether the target is redundant."""
    node = create_node(app_session, level="branch", name=name)
    weapon_duty_type = _weapon_duty_type(app_session, node=node, name=f"{name} weapon")
    covered = create_soldier(app_session, personal_number=f"{prefix}-001", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name=f"{name} range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    target_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    duty_date = source_event.date + timedelta(days=duty_offset_days)
    app_session.add(DutyAssignment(
        soldier_id=covered.id, duty_type_id=weapon_duty_type.id,
        duty_location_id=create_duty_location(app_session, name=f"{name} duty").id,
        start_date=duty_date, end_date=duty_date, status="published",
    ))
    app_session.flush()
    add_range_assignment(app_session, event=source_event, soldier_id=covered.id, is_reserve=False)
    target = add_range_assignment(app_session, event=target_event, soldier_id=covered.id, is_reserve=False)
    return covered, source_event, target


def test_reconciliation_keeps_target_covering_duty_beyond_source_window(app_session: Session) -> None:
    """The target's own validity window reaches 5 days further than the source's.
    A published weapon duty in that gap was covered by the target and cannot be
    covered by the source, so the target is not redundant."""
    from app.services.range_reconciliation import reconcile_future_range_assignments

    laser_validity = _validity_days(app_session, RangeType.laser)
    covered, source_event, target = _reconciliation_gap_fixture(
        app_session, name="reconciliation gap duty", prefix="gap",
        duty_offset_days=laser_validity + 3,
    )

    result = reconcile_future_range_assignments(
        app_session, soldier_id=covered.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == []
    assert result.unfilled_primary_count == 0
    assert result.refilled_primary_assignment_ids == []
    assert app_session.get(RangeAssignment, target.id) is not None


def test_reconciliation_still_removes_target_when_duty_falls_inside_source_window(
    app_session: Session,
) -> None:
    """Same shape, but the weapon duty is inside the source's own validity window —
    the ordinary redundancy case, which must still remove the target."""
    from app.services.range_reconciliation import reconcile_future_range_assignments

    laser_validity = _validity_days(app_session, RangeType.laser)
    covered, source_event, target = _reconciliation_gap_fixture(
        app_session, name="reconciliation covered duty", prefix="nogap",
        duty_offset_days=laser_validity - 3,
    )

    result = reconcile_future_range_assignments(
        app_session, soldier_id=covered.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == [target.id]
    assert app_session.get(RangeAssignment, target.id) is None


def test_reconciliation_locks_each_target_event_date_before_writing(
    app_session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refills land on the TARGET event's date, which the caller's source-date lock
    does not cover — reconciliation must take each target date's lock itself, in
    ascending date order so the ordering stays consistent with add_range_assignment."""
    from app.services import range_reconciliation
    from app.services.range_reconciliation import reconcile_future_range_assignments

    locked_dates: list[date] = []
    real_lock = range_reconciliation._acquire_range_assignment_date_lock

    def spy(session, *, event_date: date) -> None:
        locked_dates.append(event_date)
        real_lock(session, event_date=event_date)

    monkeypatch.setattr(range_reconciliation, "_acquire_range_assignment_date_lock", spy)

    node = create_node(app_session, level="branch", name="reconciliation target lock")
    _weapon_duty_type(app_session, node=node, name="reconciliation target lock weapon")
    covered = create_soldier(app_session, personal_number="lock-001", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="lock-002", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="reconciliation target lock range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    first_target_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    second_target_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=20), range_location_id=location.id, required_count=1,
    )
    add_range_assignment(app_session, event=source_event, soldier_id=covered.id, is_reserve=False)
    # Earliest target first: creating the day-10 assignment after the day-20 one would
    # reconcile the day-20 one away before the explicit call below can see it.
    add_range_assignment(app_session, event=first_target_event, soldier_id=covered.id, is_reserve=False)
    add_range_assignment(app_session, event=second_target_event, soldier_id=covered.id, is_reserve=False)
    locked_dates.clear()

    result = reconcile_future_range_assignments(
        app_session, soldier_id=covered.id, source_event=source_event, actor_id=None,
    )

    assert len(result.removed_assignment_ids) == 2
    assert locked_dates == [first_target_event.date, second_target_event.date]


def test_add_range_assignment_reconciles_later_duplicate(app_session: Session) -> None:
    """Creating the earlier assignment makes the later duplicate redundant: it is
    removed and its slot refilled inside the same call."""
    node = create_node(app_session, level="branch", name="wire add reconcile")
    _weapon_duty_type(app_session, node=node, name="wire add reconcile weapon")
    covered = create_soldier(app_session, personal_number="wire-001", hierarchy_node_id=node.id)
    replacement = create_soldier(app_session, personal_number="wire-002", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="wire add reconcile range")
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later = add_range_assignment(app_session, event=later_event, soldier_id=covered.id, is_reserve=False)

    add_range_assignment(app_session, event=source_event, soldier_id=covered.id, is_reserve=False)

    assert app_session.get(RangeAssignment, later.id) is None
    refilled = app_session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == later_event.id,
    )).scalars().one()
    assert refilled.soldier_id == replacement.id
    assert refilled.is_reserve is False
    assert app_session.execute(select(Notification).where(
        Notification.soldier_id == replacement.id,
        Notification.type == NotificationType.range_assignment_confirmed,
        Notification.reference_id == later_event.id,
    )).scalars().one() is not None


def test_assign_batch_reconciles_created_rows(app_session: Session) -> None:
    """Every row the batch creates reconciles forward: the primary rows clear their
    soldiers' later duplicates (primary and reserve slots alike), while a reserve row
    is not yet guaranteed coverage and leaves later assignments alone."""
    node = create_node(app_session, level="branch", name="wire batch reconcile")
    _weapon_duty_type(app_session, node=node, name="wire batch reconcile weapon")
    covered_primary = create_soldier(app_session, personal_number="wire-003", hierarchy_node_id=node.id)
    covered_reserve = create_soldier(app_session, personal_number="wire-004", hierarchy_node_id=node.id)
    batch_reserve = create_soldier(app_session, personal_number="wire-005", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="wire-006", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="wire-007", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="wire batch reconcile range")
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id,
        required_count=1, reserve_count=1,
    )
    reserve_source_target_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=12), range_location_id=location.id, required_count=1,
    )
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id,
        required_count=2, reserve_count=1,
    )
    later_primary = add_range_assignment(app_session, event=later_event, soldier_id=covered_primary.id, is_reserve=False)
    later_reserve = add_range_assignment(app_session, event=later_event, soldier_id=covered_reserve.id, is_reserve=True)
    untouched = add_range_assignment(
        app_session, event=reserve_source_target_event, soldier_id=batch_reserve.id, is_reserve=False,
    )

    assign_batch(
        app_session, event=source_event,
        primary_soldier_ids=[covered_primary.id, covered_reserve.id],
        reserve_soldier_ids=[batch_reserve.id],
    )

    assert app_session.get(RangeAssignment, later_primary.id) is None
    assert app_session.get(RangeAssignment, later_reserve.id) is None
    # The batch's reserve row is not guaranteed coverage until attendance is marked.
    assert app_session.get(RangeAssignment, untouched.id) is not None
    refills = app_session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == later_event.id,
    )).scalars().all()
    assert sorted(row.is_reserve for row in refills) == [False, True]
    assert {covered_primary.id, covered_reserve.id}.isdisjoint({row.soldier_id for row in refills})
