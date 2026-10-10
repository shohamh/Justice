"""PostgreSQL regressions for the bounded ready-snapshot cache."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from threading import Event, Thread
from time import monotonic

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from tests.helpers import auth_headers, create_soldier

_READY_SNAPSHOT_CAP = 100


def _insert_ready_snapshot(session, *, snapshot_id: uuid.UUID, binding: str, expires_at: datetime) -> None:
    session.execute(text("""
        INSERT INTO transparency_page_snapshots
          (id, binding, source_generation, source_snapshot, as_of,
           summary, can_see_exemption_aggregates, item_count, expires_at, ready)
        VALUES (
          :id, :binding, 1, pg_current_snapshot()::text, :as_of,
          '{}'::jsonb, true, 0, :expires_at, true
        )
    """), {
        "id": snapshot_id,
        "binding": binding,
        "as_of": date.today(),
        "expires_at": expires_at,
    })


def _seed_ready_snapshots(session, count: int, *, binding: str) -> list[uuid.UUID]:
    now = datetime.now(UTC)
    snapshot_ids = [uuid.uuid4() for _ in range(count)]
    for index, snapshot_id in enumerate(snapshot_ids):
        # Lower expiry timestamps are older in the cache's eviction order.
        _insert_ready_snapshot(
            session,
            snapshot_id=snapshot_id,
            binding=binding,
            expires_at=now + timedelta(minutes=index + 1),
        )
    session.commit()
    return snapshot_ids


def _create_new_snapshot(session, *, binding: str) -> uuid.UUID:
    from app.services import transparency_page_store

    snapshot, reused = transparency_page_store.register_build(
        session,
        binding=binding,
        generation=lambda _session: 2,
        capture=lambda capture_session: capture_session.execute(
            text("SELECT pg_current_snapshot()::text")
        ).scalar_one(),
        changed=lambda _session, _source_snapshot: False,
    )
    assert reused is False
    transparency_page_store.persist_rows(
        session, snapshot["id"], [], {"row_count": 0}, True
    )
    session.commit()
    return snapshot["id"]


def _wait_for_database_lock(admin_engine, backend_pid: int, completed: Event) -> bool:
    deadline = monotonic() + 5
    with admin_engine.connect() as monitor:
        while monotonic() < deadline:
            waiting = monitor.execute(text("""
                SELECT wait_event_type = 'Lock'
                FROM pg_stat_activity WHERE pid = :pid
            """), {"pid": backend_pid}).scalar_one()
            if waiting:
                return True
            if completed.wait(0.01):
                return False
    return False


def test_new_snapshot_evicts_oldest_ready_snapshot_to_keep_cap(admin_engine):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as session:
        snapshot_ids = _seed_ready_snapshots(
            session, _READY_SNAPSHOT_CAP, binding="capacity-oldest-first"
        )
        new_snapshot_id = _create_new_snapshot(
            session, binding="capacity-new-miss"
        )

        remaining_ids = set(session.execute(text("""
            SELECT id FROM transparency_page_snapshots
            WHERE expires_at > now() AND ready
        """)).scalars())

    assert len(remaining_ids) == _READY_SNAPSHOT_CAP
    assert snapshot_ids[0] not in remaining_ids
    assert set(snapshot_ids[1:]).issubset(remaining_ids)
    assert new_snapshot_id in remaining_ids


def test_publication_waits_for_cursor_locks_then_keeps_strict_cap(admin_engine):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as seed_session:
        snapshot_ids = _seed_ready_snapshots(
            seed_session, _READY_SNAPSHOT_CAP, binding="capacity-cursor-lock"
        )
    publication_started = Event()
    publication_completed = Event()
    builder_pid: list[int] = []
    builder_errors: list[Exception] = []
    new_snapshot_ids: list[uuid.UUID] = []

    def build_snapshot() -> None:
        try:
            with SessionLocal() as session:
                builder_pid.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
                snapshot, reused = transparency_page_store.register_build(
                    session,
                    binding="capacity-lock-miss",
                    generation=lambda _session: 2,
                    capture=lambda capture_session: capture_session.execute(
                        text("SELECT pg_current_snapshot()::text")
                    ).scalar_one(),
                    changed=lambda _session, _source_snapshot: False,
                )
                assert reused is False
                publication_started.set()
                transparency_page_store.persist_rows(
                    session, snapshot["id"], [], {"row_count": 0}, True
                )
                session.commit()
                new_snapshot_ids.append(snapshot["id"])
        except Exception as exc:
            builder_errors.append(exc)
        finally:
            publication_completed.set()

    builder = Thread(target=build_snapshot)
    with SessionLocal() as cursor_session:
        locked_ids = cursor_session.execute(text("""
            SELECT id FROM transparency_page_snapshots
            WHERE ready AND expires_at > now() FOR SHARE
        """)).scalars().all()
        assert set(locked_ids) == set(snapshot_ids)
        builder.start()
        try:
            assert publication_started.wait(timeout=5), "builder did not reach publication"
            waited = _wait_for_database_lock(
                admin_engine, builder_pid[0], publication_completed
            )
        finally:
            cursor_session.commit()
            builder.join(timeout=10)

    assert waited is True
    assert not builder.is_alive()
    assert builder_errors == []
    assert len(new_snapshot_ids) == 1
    with SessionLocal() as verification_session:
        remaining_ids = set(verification_session.execute(text("""
            SELECT id FROM transparency_page_snapshots
            WHERE ready AND expires_at > now()
        """)).scalars())
    assert len(remaining_ids) == _READY_SNAPSHOT_CAP
    assert snapshot_ids[0] not in remaining_ids
    assert new_snapshot_ids[0] in remaining_ids


def test_cursor_read_stays_prompt_while_cold_build_is_capturing(admin_engine):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as seed_session:
        oldest_id = _seed_ready_snapshots(
            seed_session, _READY_SNAPSHOT_CAP, binding="capacity-capture-reader"
        )[0]

    capture_started = Event()
    finish_capture = Event()
    build_errors: list[Exception] = []

    def capture(session) -> str:
        capture_started.set()
        assert finish_capture.wait(timeout=10), "capture was never released"
        return session.execute(text("SELECT pg_current_snapshot()::text")).scalar_one()

    def build_snapshot() -> None:
        try:
            with SessionLocal() as session:
                snapshot, reused = transparency_page_store.register_build(
                    session,
                    binding="capacity-capture-miss",
                    generation=lambda _session: 2,
                    capture=capture,
                    changed=lambda _session, _source_snapshot: False,
                )
                assert reused is False
                transparency_page_store.persist_rows(
                    session, snapshot["id"], [], {"row_count": 0}, True
                )
                session.commit()
        except Exception as exc:
            build_errors.append(exc)

    build_thread = Thread(target=build_snapshot)
    build_thread.start()
    try:
        assert capture_started.wait(timeout=5), "cold build did not enter capture"
        with SessionLocal() as cursor_session:
            cursor_session.execute(text("SET LOCAL lock_timeout = '300ms'"))
            start = monotonic()
            assert transparency_page_store.get_snapshot(
                cursor_session, oldest_id, lock=True
            ) is not None
            assert monotonic() - start < 1
    finally:
        finish_capture.set()
        build_thread.join(timeout=10)

    assert not build_thread.is_alive()
    assert build_errors == []


def test_publication_retires_inherited_backlog_without_cascading_chunk_deletes(admin_engine):
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as session:
        snapshot_ids = _seed_ready_snapshots(
            session, _READY_SNAPSHOT_CAP + 5, binding="capacity-bounded-work"
        )
        for snapshot_id in snapshot_ids[:6]:
            session.execute(text("""
                INSERT INTO transparency_page_snapshot_rows
                  (snapshot_id, ordinal, payload)
                VALUES (:id, 0, '[]'::jsonb)
            """), {"id": snapshot_id})
        session.commit()
        _create_new_snapshot(session, binding="capacity-bounded-miss")

        remaining_ids = set(session.execute(text("""
            SELECT id FROM transparency_page_snapshots
            WHERE expires_at > now() AND ready
        """)).scalars())
        retained_rows = session.execute(text("""
            SELECT count(*) FROM transparency_page_snapshots
        """)).scalar_one()
        retained_chunks = session.execute(text("""
            SELECT count(*) FROM transparency_page_snapshot_rows
        """)).scalar_one()

    removed_seed_ids = set(snapshot_ids) - remaining_ids
    assert len(removed_seed_ids) == 6
    assert removed_seed_ids == set(snapshot_ids[:6])
    assert len(remaining_ids) == _READY_SNAPSHOT_CAP
    # Retiring metadata avoids a potentially huge cascade over JSON chunks on
    # the request path. The bounded expired cleaner reclaims physical rows.
    assert retained_rows == _READY_SNAPSHOT_CAP + 4
    assert retained_chunks == 4


def test_concurrent_cold_publications_share_one_strict_capacity_guard(admin_engine):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as seed_session:
        _seed_ready_snapshots(seed_session, _READY_SNAPSHOT_CAP - 1, binding="capacity-race")

    first_session = SessionLocal()
    second_started = Event()
    second_completed = Event()
    second_pid: list[int] = []
    second_errors: list[Exception] = []
    second_snapshot_ids: list[uuid.UUID] = []

    def build_second() -> None:
        try:
            with SessionLocal() as session:
                second_pid.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
                snapshot, reused = transparency_page_store.register_build(
                    session,
                    binding="capacity-race-second",
                    generation=lambda _session: 2,
                    capture=lambda capture_session: capture_session.execute(
                        text("SELECT pg_current_snapshot()::text")
                    ).scalar_one(),
                    changed=lambda _session, _source_snapshot: False,
                )
                assert reused is False
                second_started.set()
                transparency_page_store.persist_rows(
                    session, snapshot["id"], [], {"row_count": 0}, True
                )
                session.commit()
                second_snapshot_ids.append(snapshot["id"])
        except Exception as exc:
            second_errors.append(exc)
        finally:
            second_completed.set()

    second = Thread(target=build_second)
    try:
        first_snapshot, reused = transparency_page_store.register_build(
            first_session,
            binding="capacity-race-first",
            generation=lambda _session: 2,
            capture=lambda capture_session: capture_session.execute(
                text("SELECT pg_current_snapshot()::text")
            ).scalar_one(),
            changed=lambda _session, _source_snapshot: False,
        )
        assert reused is False
        transparency_page_store.persist_rows(
            first_session, first_snapshot["id"], [], {"row_count": 0}, True
        )

        second.start()
        assert second_started.wait(timeout=5), "second build did not reach publication"
        second_waited = _wait_for_database_lock(
            admin_engine, second_pid[0], second_completed
        )
        first_session.commit()
    finally:
        first_session.close()
        if second.ident is not None:
            second.join(timeout=10)

    assert second_waited is True
    assert not second.is_alive()
    assert second_errors == []
    assert len(second_snapshot_ids) == 1
    with SessionLocal() as verification_session:
        remaining_ids = set(verification_session.execute(text("""
            SELECT id FROM transparency_page_snapshots
            WHERE ready AND expires_at > now()
        """)).scalars())
    assert len(remaining_ids) == _READY_SNAPSHOT_CAP
    assert first_snapshot["id"] in remaining_ids
    assert second_snapshot_ids[0] in remaining_ids


def test_reusable_snapshot_hit_repairs_inherited_over_cap_state(admin_engine):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    binding = "capacity-cache-hit"
    with SessionLocal() as seed_session:
        snapshot_ids = _seed_ready_snapshots(
            seed_session, _READY_SNAPSHOT_CAP + 1, binding=binding
        )
        seed_session.execute(text("""
            UPDATE transparency_page_snapshots
            SET source_generation = 7
            WHERE id = :id
        """), {"id": snapshot_ids[-1]})
        seed_session.commit()

    with SessionLocal() as request_session:
        snapshot, reused = transparency_page_store.register_build(
            request_session,
            binding=binding,
            generation=lambda _session: 7,
            capture=lambda _session: (_ for _ in ()).throw(AssertionError("cache miss")),
            changed=lambda _session, _source_snapshot: False,
        )
        assert reused is True
        assert snapshot["id"] == snapshot_ids[-1]

    with SessionLocal() as verification_session:
        count = verification_session.execute(text("""
            SELECT count(*) FROM transparency_page_snapshots
            WHERE expires_at > now() AND ready
        """)).scalar_one()
        retired_oldest = transparency_page_store.get_snapshot(
            verification_session, snapshot_ids[0]
        )
        preserved_hit = transparency_page_store.get_snapshot(
            verification_session, snapshot_ids[-1]
        )
    assert count == _READY_SNAPSHOT_CAP
    assert retired_oldest is None
    assert preserved_hit is not None


def test_rollback_after_eviction_restores_old_snapshot_and_discards_build(admin_engine):
    from app.services import transparency_page_store

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as seed_session:
        oldest_id = _seed_ready_snapshots(
            seed_session, _READY_SNAPSHOT_CAP, binding="capacity-rollback"
        )[0]

    with SessionLocal() as build_session:
        snapshot, reused = transparency_page_store.register_build(
            build_session,
            binding="capacity-rollback-miss",
            generation=lambda _session: 2,
            capture=lambda capture_session: capture_session.execute(
                text("SELECT pg_current_snapshot()::text")
            ).scalar_one(),
            changed=lambda _session, _source_snapshot: False,
        )
        assert reused is False
        transparency_page_store.persist_rows(
            build_session, snapshot["id"], [], {"row_count": 0}, True
        )
        assert transparency_page_store.get_snapshot(build_session, oldest_id) is None
        build_session.rollback()

    with SessionLocal() as verification_session:
        assert transparency_page_store.get_snapshot(
            verification_session, oldest_id
        ) is not None
        assert transparency_page_store.get_snapshot(
            verification_session, snapshot["id"]
        ) is None
        ready_count = verification_session.execute(text("""
            SELECT count(*) FROM transparency_page_snapshots
            WHERE ready AND expires_at > now()
        """)).scalar_one()
    assert ready_count == _READY_SNAPSHOT_CAP


def test_evicted_transparency_cursor_returns_stale_cursor(client, admin_engine, admin_session):
    import jwt

    from app.services import transparency_page_store
    from app.settings import get_settings

    admin = create_soldier(admin_session, personal_number="capacity-cursor-admin", role="admin")
    create_soldier(admin_session, personal_number="capacity-cursor-member-a")
    create_soldier(admin_session, personal_number="capacity-cursor-member-b")
    admin_session.commit()

    headers = auth_headers(admin)
    first_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1},
        headers=headers,
    )
    assert first_page.status_code == 200, first_page.text
    cursor = first_page.json()["next_cursor"]
    assert cursor is not None
    cursor_payload = jwt.decode(
        cursor,
        get_settings().jwt_secret,
        algorithms=[get_settings().jwt_algorithm],
    )
    evicted_snapshot_id = uuid.UUID(cursor_payload["snapshot_id"])

    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as session:
        now = datetime.now(UTC)
        for index in range(_READY_SNAPSHOT_CAP - 1):
            _insert_ready_snapshot(
                session,
                snapshot_id=uuid.uuid4(),
                binding=f"cursor-cap-fill-{index}",
                expires_at=now + timedelta(hours=1, minutes=index),
            )
        session.commit()

    with SessionLocal() as session:
        _create_new_snapshot(session, binding="cursor-cap-eviction-trigger")
        evicted = transparency_page_store.get_snapshot(session, evicted_snapshot_id)
    assert evicted is None

    stale_page = client.get(
        "/api/scoring/transparency/page",
        params={"page_size": 1, "cursor": cursor},
        headers=headers,
    )
    assert stale_page.status_code == 409
    assert stale_page.json()["detail"] == "stale_cursor"
