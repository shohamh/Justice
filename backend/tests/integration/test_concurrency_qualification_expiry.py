"""C16/N4 — duplicate qualification-expiry notifications (audit inventory N4).

Every web worker process runs ``qualification_expiry_worker`` (4 by default),
and they all start their daily poll at the same moment. Each check calls
``_already_notified_for_expiry`` (does a notification for this soldier, type
and expiry date exist?) and then inserts one. The check-then-insert is not
serialized across processes.

Schedule reproduced here (two independent sessions = two worker processes):
  1. both workers run the "already notified?" query for the soldier and meet
     right after it;
  2. both create the notification (plus its outbox rows) and commit.

Fixed (Task 4): each check first takes a transaction-scoped advisory try-lock
for that check. The overlapping run fails to get it and returns without
notifying; the first run's rendezvous times out and it commits one
notification.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta

from sqlalchemy import func, select

from app import qualification_expiry_worker as worker
from app.db.models import Notification, NotificationType
from tests.helpers import create_soldier


def _hook_worker_sessions(race, monkeypatch, entity, hook):
    real_scope = worker.session_scope

    @contextmanager
    def scope():
        with real_scope() as s:
            race.pause_after_select(s, entity, hook)
            yield s

    monkeypatch.setattr(worker, "session_scope", scope)


def _expired_notifications(session, soldier_id, type_):
    session.expire_all()
    return session.execute(
        select(func.count()).select_from(Notification)
        .where(Notification.soldier_id == soldier_id, Notification.type == type_)
    ).scalar_one()


def test_concurrent_mitvahim_expiry_checks_notify_once(race, admin_session, monkeypatch):
    soldier = create_soldier(admin_session, personal_number="race-qexp-m")
    soldier.last_mitvahim_date = date.today() - timedelta(days=400)
    admin_session.commit()

    after_dedupe = race.rendezvous(2, "both workers checked for an existing notification")
    _hook_worker_sessions(race, monkeypatch, Notification, after_dedupe.wait)

    outcomes = race.run(worker._check_mitvahim_expiry, worker._check_mitvahim_expiry)

    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"worker crashed: {outcome.error!r}") from outcome.error
    count = _expired_notifications(admin_session, soldier.id, NotificationType.mitvahim_expired)
    assert count == 1, f"{count} mitvahim_expired notifications for one expiry"
