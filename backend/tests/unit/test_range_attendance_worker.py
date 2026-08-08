from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager

import app.range_attendance_worker as worker


@contextmanager
def _capture_worker_log():
    """Captures records on worker.logger via a dedicated handler, independent
    of pytest's global caplog capture (which can miss records under heavy
    parallel xdist load when many other loggers are active in the same
    worker process)."""
    records: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Handler()
    # The session-autouse _apply_schema fixture runs alembic migrations
    # in-process, and alembic's env.py calls logging.config.fileConfig, which
    # (disable_existing_loggers defaults to True) sets disabled=True on every
    # logger that existed at migration time — including this module's. A
    # disabled logger drops records in Logger.handle() before reaching our
    # handler, so force it back on for the duration and restore afterwards.
    previous_level = worker.logger.level
    previous_disabled = worker.logger.disabled
    worker.logger.disabled = False
    worker.logger.addHandler(handler)
    worker.logger.setLevel(logging.INFO)
    try:
        yield records
    finally:
        worker.logger.removeHandler(handler)
        worker.logger.setLevel(previous_level)
        worker.logger.disabled = previous_disabled


def test_auto_mark_helper_calls_service_and_logs_when_marked(monkeypatch) -> None:
    calls: list[object] = []

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_auto_mark(session) -> int:
        calls.append(session)
        return 3

    monkeypatch.setattr(worker, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker, "auto_mark_present_for_elapsed_events", fake_auto_mark)

    with _capture_worker_log() as records:
        worker._auto_mark_present_for_elapsed_events()

    assert len(calls) == 1
    assert any("auto-marked 3" in record.getMessage() for record in records)


def test_auto_mark_helper_does_not_log_when_nothing_marked(monkeypatch) -> None:
    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(worker, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker, "auto_mark_present_for_elapsed_events", lambda session: 0)

    with _capture_worker_log() as records:
        worker._auto_mark_present_for_elapsed_events()

    assert not records


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
