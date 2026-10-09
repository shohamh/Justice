"""PostgreSQL races for transparency snapshot registration."""

from __future__ import annotations

from threading import Event, Thread
from time import monotonic

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


def _wait_for_advisory_lock_wait(admin_engine, backend_pid: int, completed: Event) -> bool:
    deadline = monotonic() + 5
    with admin_engine.connect() as monitor:
        while monotonic() < deadline:
            waiting = monitor.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_locks
                    WHERE pid = :pid AND locktype = 'advisory' AND NOT granted
                )
            """), {"pid": backend_pid}).scalar_one()
            if waiting:
                return True
            if completed.wait(0.01):
                return False
    return False


def test_same_binding_registration_waits_then_reuses_completed_snapshot(admin_engine):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    first_session = SessionLocal()
    second_started = Event()
    second_completed = Event()
    second_pid: list[int] = []
    second_results: list[tuple[dict, bool]] = []
    second_capture_calls: list[bool] = []
    second_errors: list[Exception] = []
    binding = "same-binding-cold-request-race"

    def generation(_session) -> int:
        return 17

    def capture(session) -> str:
        return session.execute(text("SELECT pg_current_snapshot()::text")).scalar_one()

    def capture_second_if_not_reused(_session) -> str:
        second_capture_calls.append(True)
        raise AssertionError("second request should reuse the first snapshot")

    def run_second_request() -> None:
        try:
            with SessionLocal() as session:
                second_pid.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
                second_started.set()
                second_results.append(transparency_page_store.register_build(
                    session,
                    binding=binding,
                    generation=generation,
                    capture=capture_second_if_not_reused,
                    changed=lambda _session, _snapshot: False,
                ))
        except Exception as exc:
            second_errors.append(exc)
        finally:
            second_completed.set()

    second_thread = Thread(target=run_second_request)
    try:
        first_snapshot, reused = transparency_page_store.register_build(
            first_session,
            binding=binding,
            generation=generation,
            capture=capture,
            changed=lambda _session, _snapshot: False,
        )
        assert reused is False

        transparency_page_store.persist_rows(
            first_session,
            first_snapshot["id"],
            [
                {"row_num": index, "soldier_id": f"soldier-{index}"}
                for index in range(1, 4)
            ],
            {"row_count": 3},
            True,
        )

        second_thread.start()
        assert second_started.wait(timeout=5), "second registration did not start"
        second_waited = _wait_for_advisory_lock_wait(
            admin_engine, second_pid[0], second_completed
        )

        # The first transaction owns the binding lock through persistence and
        # this commit; only then may the second request recheck for a ready row.
        first_session.commit()
    finally:
        first_session.close()
        if second_thread.ident is not None:
            second_thread.join(timeout=10)

    assert second_waited is True
    assert not second_thread.is_alive()
    assert second_completed.is_set()
    assert second_errors == []
    assert second_capture_calls == []
    assert len(second_results) == 1
    reused_snapshot, reused = second_results[0]
    assert reused is True
    assert reused_snapshot["id"] == first_snapshot["id"]

    with SessionLocal() as verification_session:
        persisted = verification_session.execute(text("""
            SELECT id, ready, item_count
            FROM transparency_page_snapshots
            WHERE binding = :binding AND expires_at > now()
        """), {"binding": binding}).one()
        assert persisted == (first_snapshot["id"], True, 3)
