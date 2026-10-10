from __future__ import annotations

import asyncio
import importlib
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _worker():
    return importlib.import_module("app.transparency_read_model_worker")


def _lock_session(acquired: bool) -> MagicMock:
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = acquired
    return session


def _set_enabled(worker, monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(
        worker, "get_settings",
        lambda: SimpleNamespace(transparency_read_model_enabled=enabled),
    )


def test_disabled_tick_does_not_open_sessions_or_build(monkeypatch):
    worker = _worker()
    _set_enabled(worker, monkeypatch, False)
    session_scope = MagicMock(side_effect=AssertionError("disabled refresh must not open a session"))
    rebuild = MagicMock()
    monkeypatch.setattr(worker, "session_scope", session_scope)
    monkeypatch.setattr(worker.model, "rebuild_generation", rebuild)

    assert worker._refresh_tick() is False

    session_scope.assert_not_called()
    rebuild.assert_not_called()


def test_stale_generation_is_built_once(monkeypatch):
    worker = _worker()
    _set_enabled(worker, monkeypatch, True)
    lock_session = _lock_session(True)
    build_session = MagicMock()
    sessions = iter((lock_session, build_session))
    monkeypatch.setattr(worker, "session_scope", lambda: nullcontext(next(sessions)))
    monkeypatch.setattr(worker.model, "capture_source_state", lambda session: (8, "snapshot"))
    monkeypatch.setattr(worker.model, "current_generation", lambda *args, **kwargs: None)
    built = {"id": "generation-8", "source_generation": 8}
    rebuild = MagicMock(return_value=built)
    monkeypatch.setattr(worker.model, "rebuild_generation", rebuild)

    assert worker._refresh_tick() is True

    rebuild.assert_called_once_with(build_session)
    lock_session.execute.assert_called_once()


def test_tick_skips_build_when_another_tick_holds_advisory_lock(monkeypatch):
    worker = _worker()
    _set_enabled(worker, monkeypatch, True)
    lock_session = _lock_session(False)
    monkeypatch.setattr(worker, "session_scope", lambda: nullcontext(lock_session))
    rebuild = MagicMock()
    monkeypatch.setattr(worker.model, "rebuild_generation", rebuild)

    assert worker._refresh_tick() is False

    rebuild.assert_not_called()


def test_current_generation_is_reused_without_rebuild(monkeypatch):
    worker = _worker()
    _set_enabled(worker, monkeypatch, True)
    lock_session = _lock_session(True)
    read_session = MagicMock()
    sessions = iter((lock_session, read_session))
    monkeypatch.setattr(worker, "session_scope", lambda: nullcontext(next(sessions)))
    monkeypatch.setattr(worker.model, "capture_source_state", lambda session: (11, "snapshot"))
    current = {"id": "current-generation", "source_generation": 11}
    monkeypatch.setattr(worker.model, "current_generation", lambda *args, **kwargs: current)
    rebuild = MagicMock()
    monkeypatch.setattr(worker.model, "rebuild_generation", rebuild)

    assert worker._refresh_tick() is True

    rebuild.assert_not_called()


def test_failed_build_can_be_retried_on_the_next_tick(monkeypatch):
    worker = _worker()
    _set_enabled(worker, monkeypatch, True)
    sessions = iter((_lock_session(True), MagicMock(), _lock_session(True), MagicMock()))
    monkeypatch.setattr(worker, "session_scope", lambda: nullcontext(next(sessions)))
    monkeypatch.setattr(worker.model, "capture_source_state", lambda session: (19, "snapshot"))
    monkeypatch.setattr(worker.model, "current_generation", lambda *args, **kwargs: None)
    rebuild = MagicMock(side_effect=[
        RuntimeError("temporary failure"),
        {"id": "recovered", "source_generation": 19},
    ])
    monkeypatch.setattr(worker.model, "rebuild_generation", rebuild)

    with pytest.raises(RuntimeError, match="temporary failure"):
        worker._refresh_tick()
    assert worker._refresh_tick() is True

    assert rebuild.call_count == 2


@pytest.mark.asyncio
async def test_worker_runs_immediately_and_propagates_poll_cancellation(monkeypatch):
    worker = _worker()
    tick = MagicMock(return_value=True)

    async def run_in_thread(function):
        return function()

    async def cancel_during_poll(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "_refresh_tick", tick)
    monkeypatch.setattr(worker.asyncio, "to_thread", run_in_thread)
    monkeypatch.setattr(worker.asyncio, "sleep", cancel_during_poll)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_transparency_read_model_worker()

    tick.assert_called_once_with()


@pytest.mark.asyncio
async def test_worker_waits_for_inflight_refresh_thread_before_cancellation(monkeypatch):
    import threading

    worker = _worker()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocked_refresh():
        started.set()
        assert release.wait(timeout=5)
        finished.set()

    monkeypatch.setattr(worker, "_refresh_tick", blocked_refresh)
    task = asyncio.create_task(worker.run_transparency_read_model_worker())
    completed_before_release = False
    cancellation_sent = False
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        cancellation_sent = True
        await asyncio.sleep(0)
        completed_before_release = task.done()
    finally:
        release.set()
        if not cancellation_sent:
            task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    assert completed_before_release is False
    assert finished.is_set()
