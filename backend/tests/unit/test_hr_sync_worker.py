from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.hr_sync_worker import _run_hr_sync_cycle, run_hr_sync_worker


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
