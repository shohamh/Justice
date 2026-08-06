from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyType,
    Notification,
    NotificationType,
    RangeEventStatus,
    RangeType,
    SystemSetting,
)
from app.services.range_reminders import send_due_range_reminders
from app.services.ranges import add_range_assignment, cancel_range_event, create_range_event
from tests.helpers import create_node, create_range_location, create_soldier


def _setup(session: Session, *, days_before: int = 3, required_count: int = 1, reserve_count: int = 0):
    session.add(SystemSetting(key="mitvachim.enabled", value=True))
    session.add(SystemSetting(key="mitvachim.reminder_days_before", value=days_before))
    session.commit()
    node = create_node(session, level="branch", name=f"reminders {days_before}-{required_count}-{reserve_count}")
    session.add(DutyType(name=f"weapon {node.name}", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    manager = create_soldier(session, personal_number=f"dm-{node.name}", role="duty_manager", hierarchy_node_id=node.id)
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=days_before),
        range_location_id=create_range_location(session, name="range").id,
        required_count=required_count, reserve_count=reserve_count,
    )
    return node, manager, event


def _notifications_for(session: Session, soldier_id) -> list[Notification]:
    return list(session.execute(select(Notification).where(Notification.soldier_id == soldier_id)).scalars())


_REMINDER_TYPES = (NotificationType.range_reminder, NotificationType.range_reminder_shortfall)


def _reminders_for(session: Session, soldier_id) -> list[Notification]:
    return [n for n in _notifications_for(session, soldier_id) if n.type in _REMINDER_TYPES]


def test_sends_reminder_exactly_at_threshold(app_session: Session) -> None:
    node, manager, event = _setup(app_session, days_before=3)
    soldier = create_soldier(app_session, personal_number="reminder-soldier", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    sent = send_due_range_reminders(app_session, today=date.today())

    assert sent == 1
    soldier_notifs = [n for n in _notifications_for(app_session, soldier.id) if n.type == NotificationType.range_reminder]
    assert len(soldier_notifs) == 1
    manager_notifs = [n for n in _notifications_for(app_session, manager.id) if n.type == NotificationType.range_reminder]
    assert len(manager_notifs) == 1
    assert app_session.get(type(event), event.id).reminder_sent_at is not None


def test_no_reminder_before_or_after_threshold(app_session: Session) -> None:
    node, manager, event = _setup(app_session, days_before=3)
    soldier = create_soldier(app_session, personal_number="reminder-soldier-2", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    sent_early = send_due_range_reminders(app_session, today=date.today() - timedelta(days=1))
    sent_late = send_due_range_reminders(app_session, today=date.today() + timedelta(days=1))

    assert sent_early == 0
    assert sent_late == 0
    assert _reminders_for(app_session, soldier.id) == []


def test_idempotent_only_sends_once(app_session: Session) -> None:
    node, manager, event = _setup(app_session, days_before=3)
    soldier = create_soldier(app_session, personal_number="reminder-soldier-3", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    first = send_due_range_reminders(app_session, today=date.today())
    second = send_due_range_reminders(app_session, today=date.today())

    assert first == 1
    assert second == 0
    soldier_notifs = [n for n in _notifications_for(app_session, soldier.id) if n.type == NotificationType.range_reminder]
    assert len(soldier_notifs) == 1


def test_notifies_both_primary_and_reserve_assignments(app_session: Session) -> None:
    node, manager, event = _setup(app_session, days_before=3, required_count=1, reserve_count=1)
    primary = create_soldier(app_session, personal_number="reminder-primary", hierarchy_node_id=node.id)
    reserve = create_soldier(app_session, personal_number="reminder-reserve", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=primary.id, is_reserve=False)
    add_range_assignment(app_session, event=event, soldier_id=reserve.id, is_reserve=True)

    sent = send_due_range_reminders(app_session, today=date.today())

    assert sent == 1
    assert any(n.type == NotificationType.range_reminder for n in _notifications_for(app_session, primary.id))
    assert any(n.type == NotificationType.range_reminder for n in _notifications_for(app_session, reserve.id))


def test_escalated_reminder_when_roster_short(app_session: Session) -> None:
    node, manager, event = _setup(app_session, days_before=3, required_count=2, reserve_count=0)
    soldier = create_soldier(app_session, personal_number="reminder-short", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    send_due_range_reminders(app_session, today=date.today())

    manager_notifs = _notifications_for(app_session, manager.id)
    assert len(manager_notifs) == 1
    assert manager_notifs[0].type == NotificationType.range_reminder_shortfall


def test_normal_reminder_when_roster_full(app_session: Session) -> None:
    node, manager, event = _setup(app_session, days_before=3, required_count=1, reserve_count=0)
    soldier = create_soldier(app_session, personal_number="reminder-full", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    send_due_range_reminders(app_session, today=date.today())

    manager_notifs = _notifications_for(app_session, manager.id)
    assert len(manager_notifs) == 1
    assert manager_notifs[0].type == NotificationType.range_reminder


def test_no_reminders_when_mitvachim_disabled(app_session: Session) -> None:
    node, manager, event = _setup(app_session, days_before=3)
    app_session.get(SystemSetting, "mitvachim.enabled").value = False
    app_session.commit()
    soldier = create_soldier(app_session, personal_number="reminder-disabled", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    sent = send_due_range_reminders(app_session, today=date.today())

    assert sent == 0
    assert _reminders_for(app_session, soldier.id) == []


def test_cancelled_events_never_remind(app_session: Session) -> None:
    node, manager, event = _setup(app_session, days_before=3)
    soldier = create_soldier(app_session, personal_number="reminder-cancelled", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    cancel_range_event(app_session, event=event)
    assert event.status == RangeEventStatus.cancelled

    sent = send_due_range_reminders(app_session, today=date.today())

    assert sent == 0
    assert _reminders_for(app_session, soldier.id) == []
