from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from app.db.models import Notification, NotificationType, Soldier
from app.qualification_expiry_worker import (
    _check_alal_expiry,
    _check_mitvahim_expiry,
    run_qualification_expiry_worker,
)
from app.services.settings_loader import set_setting
from tests.helpers import create_soldier


def test_worker_calls_both_checks_each_cycle() -> None:
    with patch("app.qualification_expiry_worker._check_mitvahim_expiry") as mock_mitvahim, \
         patch("app.qualification_expiry_worker._check_alal_expiry") as mock_alal, \
         patch("app.qualification_expiry_worker.asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        try:
            asyncio.run(run_qualification_expiry_worker())
        except asyncio.CancelledError:
            pass
    mock_mitvahim.assert_called_once()
    mock_alal.assert_called_once()


def test_check_mitvahim_expiry_notifies_at_exact_warn_day(app_session) -> None:
    set_setting(app_session, "mitvachim.live_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000101")
    s.last_mitvahim_date = date(2026, 1, 1)  # expiry = 2026-06-30; today+30 = 2026-06-30
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 5, 31)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.mitvahim_expiring_soon,
    ).one_or_none()
    assert notif is not None


def test_check_mitvahim_expiry_notifies_expired_on_exact_expiry_day(app_session) -> None:
    set_setting(app_session, "mitvachim.live_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000102")
    s.last_mitvahim_date = date(2026, 1, 1)  # expiry = 2026-06-30
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 6, 30)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.mitvahim_expired,
    ).one_or_none()
    assert notif is not None


def test_check_mitvahim_expiry_does_not_notify_outside_exact_days(app_session) -> None:
    set_setting(app_session, "mitvachim.live_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000103")
    s.last_mitvahim_date = date(2026, 1, 1)  # expiry = 2026-06-30
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 5, 1)  # neither warn-day nor expiry-day
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    count = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type.in_([NotificationType.mitvahim_expiring_soon, NotificationType.mitvahim_expired]),
    ).count()
    assert count == 0


def test_check_mitvahim_expiry_skips_departed_soldiers(app_session) -> None:
    set_setting(app_session, "mitvachim.live_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000104")
    s.last_mitvahim_date = date(2026, 1, 1)
    s.left_at = date(2026, 2, 1)
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 6, 30)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    count = app_session.query(Notification).filter(Notification.soldier_id == s.id).count()
    assert count == 0


def test_check_alal_expiry_skips_soldiers_who_are_not_alal_relevant(app_session) -> None:
    set_setting(app_session, "mitvachim.alal_validity_days", 90, actor_id=None)
    set_setting(app_session, "home.alal_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000105")
    s.last_alal_date = date(2026, 1, 1)  # expiry = 2026-04-01
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date, \
         patch("app.qualification_expiry_worker.is_alal_relevant", return_value=False):
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 4, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_alal_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.alal_expired,
    ).one_or_none()
    assert notif is None


def test_check_alal_expiry_notifies_relevant_soldier_on_expiry_day(app_session) -> None:
    set_setting(app_session, "mitvachim.alal_validity_days", 90, actor_id=None)
    set_setting(app_session, "home.alal_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000106")
    s.last_alal_date = date(2026, 1, 1)  # expiry = 2026-04-01
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date, \
         patch("app.qualification_expiry_worker.is_alal_relevant", return_value=True):
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 4, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_alal_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.alal_expired,
    ).one_or_none()
    assert notif is not None


def test_check_mitvahim_expiry_commits_and_persists_after_session_close(app_session, app_engine) -> None:
    """Regression coverage for a missing session.commit(), mirroring the
    equivalent rank_advancement_worker test: calls the REAL (unmocked)
    _check_mitvahim_expiry, which opens its own session via the real
    session_scope() and must commit before returning."""
    s = create_soldier(app_session, personal_number="1000107")
    s.last_mitvahim_date = date.today() - timedelta(days=180)  # expires today with default 180-day validity
    app_session.commit()
    soldier_id = s.id

    _check_mitvahim_expiry()  # real session_scope() -- not mocked/patched

    FreshSession = sessionmaker(bind=app_engine, expire_on_commit=False)
    with FreshSession() as fresh:
        notif = fresh.query(Notification).filter(
            Notification.soldier_id == soldier_id,
            Notification.type == NotificationType.mitvahim_expired,
        ).one_or_none()
        assert notif is not None


def test_check_mitvahim_expiry_catches_up_after_a_missed_cycle(app_session) -> None:
    set_setting(app_session, "mitvachim.live_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000108")
    s.last_mitvahim_date = date(2026, 1, 1)  # expiry = 2026-06-30
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 7, 5)  # 5 days AFTER expiry -- a missed cycle
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.mitvahim_expired,
    ).one_or_none()
    assert notif is not None


def test_check_mitvahim_expiry_does_not_duplicate_on_a_second_run(app_session) -> None:
    set_setting(app_session, "mitvachim.live_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000109")
    s.last_mitvahim_date = date(2026, 1, 1)  # expiry = 2026-06-30
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 6, 30)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()
        _check_mitvahim_expiry()  # simulate a second run (e.g. a restart) on the same day

    count = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.mitvahim_expired,
    ).count()
    assert count == 1
