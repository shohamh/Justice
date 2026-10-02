"""C2 — range reminders sent once per worker process (audit inventory R7).

Every uvicorn process runs the range-reminder worker. ``send_due_range_reminders``
selects planned events with ``reminder_sent_at IS NULL`` without a lock, creates
the reminder notifications (plus Telegram/email outbox rows), and only then sets
``reminder_sent_at``.

Schedule reproduced here (two independent sessions = two worker processes):
  1. worker A and worker B each SELECT the due event (reminder_sent_at IS NULL);
  2. both meet at a rendezvous right after that SELECT returns;
  3. both create the reminders, set reminder_sent_at and commit (B's UPDATE of
     the event row waits for A's commit, then overwrites it).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db.models import (
    DutyType,
    Notification,
    NotificationType,
    RangeAssignment,
    RangeEvent,
    RangeType,
    SystemSetting,
)
from app.services.range_reminders import send_due_range_reminders
from tests.helpers import create_node, create_range_location, create_soldier

_DAYS_BEFORE = 3


def _seed_due_event(session):
    session.add(SystemSetting(key="mitvachim.enabled", value=True))
    session.add(SystemSetting(key="mitvachim.reminder_days_before", value=_DAYS_BEFORE))
    session.commit()
    node = create_node(session, level="branch", name="race-reminders")
    session.add(DutyType(name="race-reminders weapon", score_per_day=Decimal("1.00"),
                         requires_weapon=True, eligible_node_ids=[node.id]))
    manager = create_soldier(session, personal_number="race-rem-dm", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(session, personal_number="race-rem-soldier", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type=RangeType.laser,
        date=date.today() + timedelta(days=_DAYS_BEFORE),
        range_location_id=create_range_location(session, name="race-reminders range").id,
        required_count=1, reserve_count=0,
    )
    session.add(event)
    session.flush()
    session.add(RangeAssignment(range_event_id=event.id, soldier_id=soldier.id, is_reserve=False))
    session.commit()
    return event, soldier, manager


def _reminder_count(session, soldier_id) -> int:
    return session.execute(
        select(func.count()).select_from(Notification).where(
            Notification.soldier_id == soldier_id,
            Notification.type.in_((NotificationType.range_reminder, NotificationType.range_reminder_shortfall)),
        )
    ).scalar_one()


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="C2: concurrent send_due_range_reminders runs each send the same event's reminders",
)
def test_concurrent_reminder_workers_notify_each_recipient_once(race, admin_session):
    event, soldier, manager = _seed_due_event(admin_session)
    after_event_read = race.rendezvous(2, "both workers read the due event")

    def worker():
        s = race.session()
        race.pause_after_select(s, RangeEvent, after_event_read.wait)
        sent = send_due_range_reminders(s, today=date.today())
        s.commit()
        return sent

    outcomes = race.run(worker, worker)

    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"worker crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    assert admin_session.get(RangeEvent, event.id).reminder_sent_at is not None
    soldier_reminders = _reminder_count(admin_session, soldier.id)
    manager_reminders = _reminder_count(admin_session, manager.id)
    assert (soldier_reminders, manager_reminders) == (1, 1), (
        f"worker results={[o.value for o in outcomes]}; soldier got {soldier_reminders} reminders, "
        f"manager got {manager_reminders}"
    )
