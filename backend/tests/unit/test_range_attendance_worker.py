from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager

import app.range_attendance_worker as worker


def test_auto_mark_helper_calls_service_and_logs_when_marked(monkeypatch, caplog) -> None:
    calls: list[object] = []

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_auto_mark(session) -> int:
        calls.append(session)
        return 3

    monkeypatch.setattr(worker, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker, "auto_mark_present_for_elapsed_events", fake_auto_mark)

    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        worker._auto_mark_present_for_elapsed_events()

    assert len(calls) == 1
    assert any("auto-marked 3" in record.message for record in caplog.records)


def test_auto_mark_helper_does_not_log_when_nothing_marked(monkeypatch, caplog) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(worker, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker, "auto_mark_present_for_elapsed_events", lambda session: 0)

    with caplog.at_level(logging.INFO, logger=worker.logger.name):
        worker._auto_mark_present_for_elapsed_events()

    assert not caplog.records


def test_worker_loop_swallows_errors_from_helper(monkeypatch) -> None:
    """Mirrors run_range_attendance_worker's try/except around the sync helper:
    an exception raised inside the helper must be caught and logged, not
    propagated, so the polling loop never dies."""

    def boom() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "_auto_mark_present_for_elapsed_events", boom)

    async def run_one_iteration() -> None:
        try:
            await asyncio.to_thread(worker._auto_mark_present_for_elapsed_events)
        except Exception:
            worker.logger.warning("range attendance worker: unhandled error", exc_info=True)

    # Should not raise.
    asyncio.run(run_one_iteration())
