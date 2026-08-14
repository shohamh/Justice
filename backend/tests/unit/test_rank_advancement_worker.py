from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import patch

from app.rank_advancement_worker import (
    _promote_due_soldiers,
    _promote_soldier,
    _warn_upcoming_soldiers,
    run_rank_advancement_worker,
)
from app.services.rank_advancement import upsert_interval
from tests.helpers import create_soldier


def test_worker_calls_promote_and_warn_each_cycle() -> None:
    with patch("app.rank_advancement_worker._promote_due_soldiers") as mock_promote, \
         patch("app.rank_advancement_worker._warn_upcoming_soldiers") as mock_warn, \
         patch("app.rank_advancement_worker.asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        try:
            asyncio.run(run_rank_advancement_worker())
        except asyncio.CancelledError:
            pass
    mock_promote.assert_called_once()
    mock_warn.assert_called_once()


def test_promote_due_soldiers_advances_rank_and_chains_next_date(app_session) -> None:
    s = create_soldier(app_session, personal_number="1000001")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, actor_id=None)
    app_session.flush()

    _promote_soldier(app_session, s, today=date(2026, 1, 1))

    assert s.rank == "רבט"
    assert s.next_rank_date == date(2026, 9, 1)
    assert s.next_rank_date_overridden is False
    assert s.current_rank_since == date(2026, 1, 1)


def test_promote_due_soldiers_stops_at_top_of_ladder(app_session) -> None:
    s = create_soldier(app_session, personal_number="1000002")
    s.rank = "רנג"  # top of enlisted ladder
    s.next_rank_date = date(2026, 1, 1)
    app_session.flush()

    _promote_soldier(app_session, s, today=date(2026, 1, 1))

    assert s.rank == "רנג"
    assert s.next_rank_date is None


def test_promote_due_soldiers_skips_discharged_soldiers(app_session) -> None:
    s = create_soldier(app_session, personal_number="1000003")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    s.discharge_date = date(2025, 12, 1)
    app_session.flush()

    with patch("app.rank_advancement_worker.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = app_session
        _promote_due_soldiers()

    assert s.rank == "טוראי"  # unchanged


def test_promote_due_soldiers_skips_departed_soldiers(app_session) -> None:
    s = create_soldier(app_session, personal_number="1000004")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    s.left_at = date(2025, 12, 1)
    app_session.flush()

    with patch("app.rank_advancement_worker.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = app_session
        _promote_due_soldiers()

    assert s.rank == "טוראי"  # unchanged


def test_promote_due_soldiers_promotes_eligible_soldier(app_session) -> None:
    s = create_soldier(app_session, personal_number="1000005")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=8, actor_id=None)
    app_session.flush()

    with patch("app.rank_advancement_worker.session_scope") as mock_scope:
        mock_scope.return_value.__enter__.return_value = app_session
        _promote_due_soldiers()

    assert s.rank == "רבט"


def test_warn_upcoming_soldiers_notifies_at_exact_warning_day(app_session) -> None:
    from app.db.models import Notification, NotificationType

    s = create_soldier(app_session, personal_number="1000006")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 8)  # today + 7 days
    app_session.flush()

    with patch("app.rank_advancement_worker.session_scope") as mock_scope, \
         patch("app.rank_advancement_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 1, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _warn_upcoming_soldiers()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.rank_advancement_soon,
    ).one_or_none()
    assert notif is not None


def test_warn_upcoming_soldiers_ignores_soldiers_outside_exact_day(app_session) -> None:
    from app.db.models import Notification, NotificationType

    s = create_soldier(app_session, personal_number="1000007")
    s.rank = "טוראי"
    s.next_rank_date = date(2026, 1, 9)  # today + 8 days, not exactly the warning window
    app_session.flush()

    with patch("app.rank_advancement_worker.session_scope") as mock_scope, \
         patch("app.rank_advancement_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 1, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _warn_upcoming_soldiers()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.rank_advancement_soon,
    ).one_or_none()
    assert notif is None
