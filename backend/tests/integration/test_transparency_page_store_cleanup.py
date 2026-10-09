"""PostgreSQL regressions for bounded transparency snapshot cleanup."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


def _insert_snapshot(
    session,
    *,
    snapshot_id: uuid.UUID,
    binding: str,
    source_snapshot: str = "0:0:",
    expires_at: str = "now() + interval '20 minutes'",
    ready: bool = True,
) -> None:
    session.execute(text(f"""
        INSERT INTO transparency_page_snapshots
          (id, binding, source_generation, source_snapshot, as_of, expires_at, ready)
        VALUES (:id, :binding, 1, :source_snapshot, :as_of, {expires_at}, :ready)
    """), {
        "id": snapshot_id,
        "binding": binding,
        "source_snapshot": source_snapshot,
        "as_of": date.today(),
        "ready": ready,
    })


def test_reusable_snapshot_does_not_wait_for_cleanup_exclusive_lock(admin_engine):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    snapshot_id = uuid.uuid4()
    with SessionLocal() as lock_session, SessionLocal() as request_session:
        _insert_snapshot(lock_session, snapshot_id=snapshot_id, binding="cache-hit")
        lock_session.commit()
        lock_session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": transparency_page_store._LOCK_KEY},
        )
        request_session.execute(text("SET LOCAL lock_timeout = '200ms'"))

        snapshot, reused = transparency_page_store.register_build(
            request_session,
            binding="cache-hit",
            generation=lambda _session: 1,
            capture=lambda _session: (_ for _ in ()).throw(AssertionError("cache miss")),
            changed=lambda _session, _snapshot: False,
        )

        assert reused is True
        assert snapshot["id"] == snapshot_id


def test_cleanup_skips_while_registration_holds_shared_lock(admin_engine):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    inserted_ids: list[uuid.UUID] = []
    cleanup_attempts: list[bool] = []

    def capture(registration_session) -> str:
        expired_id = uuid.uuid4()
        inserted_ids.append(expired_id)
        with SessionLocal() as seed_session:
            _insert_snapshot(
                seed_session,
                snapshot_id=expired_id,
                binding="expired-during-registration",
                expires_at="now() - interval '1 second'",
            )
            seed_session.commit()

        with SessionLocal() as cleanup_session:
            cleanup_session.execute(text("SET LOCAL lock_timeout = '200ms'"))
            cleanup_attempts.append(transparency_page_store.cleanup_expired(cleanup_session))
            cleanup_session.commit()
            retained = cleanup_session.execute(text("""
                SELECT count(*) FROM transparency_page_snapshots WHERE id = :id
            """), {"id": expired_id}).scalar_one()
        assert retained == 1
        return registration_session.execute(
            text("SELECT pg_current_snapshot()::text")
        ).scalar_one()

    with SessionLocal() as registration_session:
        transparency_page_store.register_build(
            registration_session,
            binding="new-registration",
            generation=lambda _session: 1,
            capture=capture,
            changed=lambda _session, _snapshot: False,
        )

    assert cleanup_attempts == [False]
    assert len(inserted_ids) == 1


def test_cleanup_deletes_bounded_batches_and_retains_live_snapshot_journal(
    admin_engine,
):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    # Snapshot deletion cascades into saved row payloads; five expired parents
    # make the two-snapshot per-cleanup cap observable without a large fixture.
    expired_ids = [uuid.uuid4() for _ in range(5)]
    live_snapshot_id = uuid.uuid4()

    with SessionLocal() as session:
        for expired_id in expired_ids:
            _insert_snapshot(
                session,
                snapshot_id=expired_id,
                binding="expired-batch",
                expires_at="now() - interval '1 second'",
            )
        session.execute(text("""
            INSERT INTO transparency_source_change_journal (transaction_id)
            SELECT value::text::xid8 FROM generate_series(1, 5) AS value
        """))
        captured = session.execute(
            text("SELECT pg_current_snapshot()::text")
        ).scalar_one()
        session.commit()

    with SessionLocal() as writer_session:
        writer_session.execute(text("""
            UPDATE system_settings SET value = value WHERE key = 'auth.session_minutes'
        """))
        live_event = writer_session.execute(
            text("SELECT pg_current_xact_id()::text")
        ).scalar_one()
        writer_session.commit()

    with SessionLocal() as session:
        _insert_snapshot(
            session,
            snapshot_id=live_snapshot_id,
            binding="live-capture",
            source_snapshot=captured,
        )
        session.commit()

    with SessionLocal() as cleanup_session:
        transparency_page_store.cleanup_expired(cleanup_session)
        cleanup_session.commit()

        assert cleanup_session.execute(text("""
            SELECT count(*) FROM transparency_page_snapshots
            WHERE binding = 'expired-batch'
        """)).scalar_one() >= 3
        assert cleanup_session.execute(text("""
            SELECT count(*) FROM transparency_source_change_journal
            WHERE transaction_id IN ('1'::xid8, '2'::xid8, '3'::xid8, '4'::xid8, '5'::xid8)
        """)).scalar_one() >= 3
        assert cleanup_session.execute(text("""
            SELECT count(*) FROM transparency_source_change_journal
            WHERE transaction_id = CAST(:xid AS xid8)
        """), {"xid": live_event}).scalar_one() == 1

        for _ in expired_ids:
            transparency_page_store.cleanup_expired(cleanup_session)
            cleanup_session.commit()
        assert cleanup_session.execute(text("""
            SELECT count(*) FROM transparency_page_snapshots
            WHERE binding = 'expired-batch'
        """)).scalar_one() == 0
        assert cleanup_session.execute(text("""
            SELECT count(*) FROM transparency_source_change_journal
            WHERE transaction_id IN ('1'::xid8, '2'::xid8, '3'::xid8, '4'::xid8, '5'::xid8)
        """)).scalar_one() == 0
        assert cleanup_session.execute(text("""
            SELECT count(*) FROM transparency_source_change_journal
            WHERE transaction_id = CAST(:xid AS xid8)
        """), {"xid": live_event}).scalar_one() == 1
