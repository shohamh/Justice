from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.hr_sync_worker import _run_hr_sync_cycle, _run_hr_sync_cycle_in_own_session, run_hr_sync_worker


def test_worker_calls_sync_cycle_each_wake(app_session) -> None:
    with patch("app.hr_sync_worker._run_hr_sync_cycle_in_own_session") as mock_cycle, \
         patch("app.hr_sync_worker.asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        try:
            asyncio.run(run_hr_sync_worker())
        except asyncio.CancelledError:
            pass
    mock_cycle.assert_called_once()


def test_worker_survives_exception_from_own_session_cycle(app_session) -> None:
    with patch(
        "app.hr_sync_worker._run_hr_sync_cycle_in_own_session",
        side_effect=RuntimeError("boom"),
    ) as mock_cycle, patch(
        "app.hr_sync_worker.asyncio.sleep", side_effect=[None, None, asyncio.CancelledError]
    ):
        try:
            asyncio.run(run_hr_sync_worker())
        except asyncio.CancelledError:
            pass
    # Two wakes reached _run_hr_sync_cycle_in_own_session before the loop was
    # cancelled on the third sleep -- proving the RuntimeError from the first
    # call did not kill the loop.
    assert mock_cycle.call_count == 2


def test_run_hr_sync_cycle_skips_when_hr_not_configured(app_session) -> None:
    with patch("app.hr_sync_worker.get_settings") as mock_settings:
        mock_settings.return_value.hr_sync_enabled = False
        with patch("app.hr_sync_worker.run_hierarchy_sync") as mock_hierarchy, \
             patch("app.hr_sync_worker.run_person_sync") as mock_person:
            asyncio.run(_run_hr_sync_cycle(app_session))
    mock_hierarchy.assert_not_called()
    mock_person.assert_not_called()


def test_run_hr_sync_cycle_runs_hierarchy_then_person_sync(app_session) -> None:
    with patch("app.hr_sync_worker.get_settings") as mock_settings:
        mock_settings.return_value.hr_sync_enabled = True
        mock_settings.return_value.hr_api_base_url = "https://hr.example"
        mock_settings.return_value.hr_api_key = "key"
        mock_settings.return_value.hr_api_ca_bundle_path = ""
        mock_settings.return_value.hr_api_page_size = 200
        with patch("app.hr_sync_worker.HrApiClient") as mock_client_cls, \
             patch("app.hr_sync_worker.run_hierarchy_sync", new_callable=AsyncMock) as mock_hierarchy, \
             patch("app.hr_sync_worker.run_person_sync", new_callable=AsyncMock) as mock_person:
            call_order = []
            mock_hierarchy.side_effect = lambda *a, **k: call_order.append("hierarchy")
            mock_person.side_effect = lambda *a, **k: call_order.append("person")
            asyncio.run(_run_hr_sync_cycle(app_session))
    mock_client_cls.assert_called_once_with(
        "https://hr.example", "key", ca_bundle_path="", page_size=200,
    )
    mock_hierarchy.assert_called_once()
    mock_person.assert_called_once()
    assert call_order == ["hierarchy", "person"]


def test_run_hr_sync_cycle_in_own_session_opens_session_and_returns_poll_hours(app_session) -> None:
    """Exercises the real (unmocked) session_scope() + get_setting_int() +
    asyncio.run() plumbing -- not just the inner _run_hr_sync_cycle that the
    other tests here patch around. HR sync is left disabled (no HR_API_*
    settings in the test environment), so this only proves the wrapper opens
    its own session, reads the configured poll interval, commits, and returns
    it -- without needing a real HR API client."""
    from app.services.settings_loader import set_setting

    set_setting(app_session, "hr_sync.poll_hours", "9", actor_id=None)
    app_session.commit()

    poll_hours = _run_hr_sync_cycle_in_own_session()

    assert poll_hours == 9


def test_run_hr_sync_cycle_in_own_session_skips_when_lock_held(app_session) -> None:
    """A concurrent manual "run sync now" (or another cron process) holds the
    shared advisory lock -- the cron cycle must skip this wake rather than
    block waiting for it."""
    from sqlalchemy import text
    from app.hr_sync_worker import _SYNC_LOCK_KEY
    from app.services.settings_loader import set_setting

    set_setting(app_session, "hr_sync.poll_hours", "9", actor_id=None)
    app_session.commit()

    # Hold the lock on a connection dedicated to it (not app_session's own
    # connection, which SQLAlchemy would silently return to the pool on any
    # commit, detaching the later unlock from the connection that actually
    # holds the lock and leaking it forever). This mirrors the fix in
    # app/hr_sync_worker.py's _sync_lock.
    engine = app_session.get_bind()
    with engine.connect() as lock_conn:
        lock_conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _SYNC_LOCK_KEY})
        try:
            with patch("app.hr_sync_worker.run_hierarchy_sync") as mock_hierarchy, \
                 patch("app.hr_sync_worker.run_person_sync") as mock_person:
                poll_hours = _run_hr_sync_cycle_in_own_session()
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _SYNC_LOCK_KEY})

    assert poll_hours == 9
    mock_hierarchy.assert_not_called()
    mock_person.assert_not_called()


def test_run_hr_sync_cycle_in_own_session_releases_lock_despite_internal_commits(app_session) -> None:
    """Regression test for a real production deadlock: run_hierarchy_sync/
    run_person_sync commit their own session internally several times while
    the lock is meant to be held. SQLAlchemy returns a Session's connection
    to the pool on every commit(), so if the lock were taken/released on
    that same ORM session (as an earlier version of this code did), the
    unlock could run on a *different* physical connection than the one that
    took the lock -- silently leaking it forever. Prove the lock is
    genuinely free afterward by acquiring it from a completely separate
    connection."""
    from sqlalchemy import text
    from app.hr_sync_worker import _SYNC_LOCK_KEY
    from app.services.settings_loader import set_setting

    set_setting(app_session, "hr_sync.poll_hours", "9", actor_id=None)
    app_session.commit()

    def _hierarchy_side_effect(session, client):
        session.commit()

    def _person_side_effect(session, client):
        session.commit()

    with patch("app.hr_sync_worker.get_settings") as mock_settings:
        mock_settings.return_value.hr_sync_enabled = True
        mock_settings.return_value.hr_api_base_url = "https://hr.example"
        mock_settings.return_value.hr_api_key = "key"
        mock_settings.return_value.hr_api_ca_bundle_path = ""
        mock_settings.return_value.hr_api_page_size = 200
        with patch("app.hr_sync_worker.HrApiClient"), \
             patch("app.hr_sync_worker.run_hierarchy_sync", new_callable=AsyncMock, side_effect=_hierarchy_side_effect), \
             patch("app.hr_sync_worker.run_person_sync", new_callable=AsyncMock, side_effect=_person_side_effect):
            _run_hr_sync_cycle_in_own_session()

    engine = app_session.get_bind()
    with engine.connect() as probe_conn:
        reacquired = bool(
            probe_conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _SYNC_LOCK_KEY}).scalar()
        )
        if reacquired:
            probe_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _SYNC_LOCK_KEY})
    assert reacquired, "lock was not released -- it leaked on a pooled connection"


def test_run_hr_sync_cycle_logs_and_swallows_exceptions(app_session) -> None:
    with patch("app.hr_sync_worker.get_settings") as mock_settings:
        mock_settings.return_value.hr_sync_enabled = True
        mock_settings.return_value.hr_api_base_url = "https://hr.example"
        mock_settings.return_value.hr_api_key = "key"
        mock_settings.return_value.hr_api_ca_bundle_path = ""
        mock_settings.return_value.hr_api_page_size = 200
        with patch("app.hr_sync_worker.HrApiClient"), \
             patch("app.hr_sync_worker.run_hierarchy_sync", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            # Must not raise -- the cycle catches and logs.
            asyncio.run(_run_hr_sync_cycle(app_session))
