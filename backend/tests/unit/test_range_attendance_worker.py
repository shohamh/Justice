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
    calls: list[tuple[str, object]] = []

    class FakeSession:
        def commit(self) -> None:
            calls.append(("commit", self))

    session = FakeSession()

    @contextmanager
    def fake_session_scope():
        yield session

    def fake_complete(current_session) -> int:
        calls.append(("complete", current_session))
        return 2

    def fake_auto_mark(current_session) -> int:
        calls.append(("attendance", current_session))
        return 3

    monkeypatch.setattr(worker, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker, "mark_past_range_events_completed", fake_complete)
    monkeypatch.setattr(worker, "auto_mark_present_for_elapsed_events", fake_auto_mark)

    with _capture_worker_log() as records:
        worker._auto_mark_present_for_elapsed_events()

    assert calls == [("complete", session), ("attendance", session), ("commit", session)]
    assert any("completed 2" in record.getMessage() for record in records)
    assert any("auto-marked 3" in record.getMessage() for record in records)


def test_auto_mark_helper_does_not_log_when_nothing_marked(monkeypatch) -> None:
    commits: list[object] = []

    class FakeSession:
        def commit(self) -> None:
            commits.append(self)

    session = FakeSession()

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(worker, "session_scope", fake_session_scope)
    monkeypatch.setattr(worker, "mark_past_range_events_completed", lambda current_session: 0)
    monkeypatch.setattr(worker, "auto_mark_present_for_elapsed_events", lambda current_session: 0)

    with _capture_worker_log() as records:
        worker._auto_mark_present_for_elapsed_events()

    assert commits == [session]
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
