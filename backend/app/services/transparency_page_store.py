"""Persist ordered transparency pages and retain journal events needed by live views."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_LOCK_KEY = 5682644037709134765
_CAPACITY_LOCK_KEY = 5682644037709134766
_BINDING_LOCK_SEED = 237816388093461712
_ROWS_PER_CHUNK = 100
_CHUNK_BATCH = 500
_MAX_READY_SNAPSHOTS = 100
# Each expired snapshot cascades to all its saved rows; cap each opportunistic
# cleanup at two snapshots so a large stale cache cannot dominate a page miss.
_CLEANUP_BATCH_SIZE = 2


def _lock_registration(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": _LOCK_KEY})


def _lock_binding_registration(session: Session, binding: str) -> None:
    session.execute(text("""
        SELECT pg_advisory_xact_lock(hashtextextended(:binding, :seed))
    """), {"binding": binding, "seed": _BINDING_LOCK_SEED})


def cleanup_expired(session: Session) -> bool:
    """Try one bounded cleanup batch without delaying snapshot registration.

    Snapshot registration holds a shared transaction lock from capture through
    ready-snapshot commit (or rollback). Cleanup takes the same lock exclusively,
    but only with a nonblocking try, so it skips work while any build is active.
    Uncommitted journal rows are invisible to this DELETE; a committed event
    invisible to a live capture remains protected until that capture expires.
    Snapshot deletes cascade to every persisted row, so each batch is limited
    to two snapshots to keep this work small on a first-page cache miss.
    """
    acquired = session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _LOCK_KEY}
    ).scalar_one()
    if not acquired:
        return False

    session.execute(text("""
        WITH expired AS (
            SELECT id
            FROM transparency_page_snapshots
            WHERE expires_at <= now()
            ORDER BY expires_at, id
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        )
        DELETE FROM transparency_page_snapshots AS snapshot
        USING expired
        WHERE snapshot.id = expired.id
    """), {"batch_size": _CLEANUP_BATCH_SIZE})
    session.execute(text("""
        WITH pruneable AS (
            SELECT journal.transaction_id
            FROM transparency_source_change_journal AS journal
            WHERE NOT EXISTS (
                SELECT 1 FROM transparency_page_snapshots AS snapshot
                WHERE snapshot.expires_at > now()
                  AND journal.transaction_id >= pg_snapshot_xmin(
                      CAST(snapshot.source_snapshot AS pg_snapshot)
                  )
                  AND NOT pg_visible_in_snapshot(
                      journal.transaction_id, CAST(snapshot.source_snapshot AS pg_snapshot)
                  )
            )
            ORDER BY journal.transaction_id
            LIMIT :batch_size
            FOR UPDATE OF journal SKIP LOCKED
        )
        DELETE FROM transparency_source_change_journal AS journal
        USING pruneable
        WHERE journal.transaction_id = pruneable.transaction_id
    """), {"batch_size": _CLEANUP_BATCH_SIZE})
    return True


def get_snapshot(session: Session, snapshot_id: uuid.UUID, *, lock: bool = False) -> dict | None:
    suffix = " FOR SHARE" if lock else ""
    row = session.execute(text("""
        SELECT id, binding, source_generation, source_snapshot, as_of, summary,
               can_see_exemption_aggregates, item_count, expires_at, ready
        FROM transparency_page_snapshots
        WHERE id = :id AND expires_at > now()
    """ + suffix), {"id": snapshot_id}).mappings().one_or_none()
    return dict(row) if row else None


def find_reusable(session: Session, binding: str, generation: int, as_of: date) -> dict | None:
    row = session.execute(text("""
        SELECT id FROM transparency_page_snapshots
        WHERE binding = :binding AND source_generation = :generation
          AND as_of = :as_of AND ready AND expires_at > now()
        ORDER BY expires_at DESC LIMIT 1
        FOR SHARE
    """), {"binding": binding, "generation": generation, "as_of": as_of}).scalar_one_or_none()
    return get_snapshot(session, row, lock=True) if row else None


def _lock_capacity(session: Session) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CAPACITY_LOCK_KEY}
    )


def _has_excess_ready(session: Session) -> bool:
    return session.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM transparency_page_snapshots
            WHERE ready AND expires_at > now()
            OFFSET :capacity LIMIT 1
        )
    """), {"capacity": _MAX_READY_SNAPSHOTS}).scalar_one()


def _retire_for_capacity(
    session: Session, *, reserve: int, preserve_id: uuid.UUID | None = None,
) -> int:
    """Hide old live snapshots while deferring their chunk deletion to cleanup.

    The caller holds the transaction-scoped capacity lock. Retiring metadata
    can touch every row in an inherited over-cap backlog, but it never
    cascades through the potentially large JSON chunk table on this request.
    Expired cleanup deletes the physical rows in bounded batches later.
    """
    ready_count = session.execute(text("""
        SELECT count(*)
        FROM transparency_page_snapshots
        WHERE ready AND expires_at > now()
    """)).scalar_one()
    needed = max(0, ready_count - _MAX_READY_SNAPSHOTS + reserve)
    if not needed:
        return 0

    result = session.execute(text("""
        WITH victims AS (
            SELECT id
            FROM transparency_page_snapshots
            WHERE ready AND expires_at > now() AND id IS DISTINCT FROM :preserve_id
            ORDER BY expires_at, id
            LIMIT :needed
            FOR UPDATE
        )
        UPDATE transparency_page_snapshots AS snapshot
        SET ready = false, expires_at = now()
        FROM victims WHERE snapshot.id = victims.id
    """), {"needed": needed, "preserve_id": preserve_id})
    return max(0, result.rowcount or 0)


def _repair_excess_ready(
    session: Session, *, binding: str, as_of: date,
    generation: Callable[[Session], int],
    changed: Callable[[Session, str], bool],
) -> dict | None:
    """Repair inherited excess without holding a reusable row's share lock.

    A candidate found before the capacity lock may be evicted while waiting.
    Recheck generation and freshness after acquiring the lock, then preserve
    the selected candidate while retiring other snapshots.
    """
    session.commit()
    _lock_capacity(session)
    source_generation = generation(session)
    cached = find_reusable(session, binding, source_generation, as_of)
    if cached and changed(session, cached["source_snapshot"]):
        cached = None
    _retire_for_capacity(
        session, reserve=0, preserve_id=cached["id"] if cached else None
    )
    session.commit()
    return cached


def register_build(
    session: Session, *, binding: str,
    generation: Callable[[Session], int],
    capture: Callable[[Session], str],
    changed: Callable[[Session, str], bool],
) -> tuple[dict, bool]:
    as_of = date.today()
    while True:
        if _has_excess_ready(session):
            cached = _repair_excess_ready(
                session, binding=binding, as_of=as_of,
                generation=generation, changed=changed,
            )
            if cached:
                return cached, True

        source_generation = generation(session)
        cached = find_reusable(session, binding, source_generation, as_of)
        if cached and not changed(session, cached["source_snapshot"]):
            if _has_excess_ready(session):
                session.commit()
                continue
            session.commit()
            return cached, True

        # Release a reusable candidate's row lock before trying cleanup.
        # Its exclusive advisory lock is nonblocking; cache hits skip it.
        session.commit()
        cleanup_expired(session)
        session.commit()

        # Same-binding cold requests wait for the first complete publication.
        _lock_binding_registration(session, binding)

        # Keep journal events needed by this capture until commit or rollback.
        _lock_registration(session)
        source_generation = generation(session)
        cached = find_reusable(session, binding, source_generation, as_of)
        if cached and not changed(session, cached["source_snapshot"]):
            if _has_excess_ready(session):
                session.commit()
                continue
            session.commit()
            return cached, True
        if _has_excess_ready(session):
            session.commit()
            continue
        break

    source_snapshot = capture(session)
    snapshot_id = uuid.uuid4()
    session.execute(text("""
        INSERT INTO transparency_page_snapshots
          (id, binding, source_generation, source_snapshot, as_of, expires_at, ready)
        VALUES (:id, :binding, :generation, :snapshot, :as_of,
                now() + interval '1 hour', false)
    """), {"id": snapshot_id, "binding": binding, "generation": source_generation,
           "snapshot": source_snapshot, "as_of": as_of})
    registered = get_snapshot(session, snapshot_id)
    assert registered is not None
    return registered, False


def persist_rows(
    session: Session, snapshot_id: uuid.UUID, rows: list[dict],
    summary: dict, can_see_exemption_aggregates: bool,
) -> None:
    chunks = [rows[start:start + _ROWS_PER_CHUNK] for start in range(0, len(rows), _ROWS_PER_CHUNK)]
    statement = text("""
        INSERT INTO transparency_page_snapshot_rows (snapshot_id, ordinal, payload)
        VALUES (:id, :ordinal, CAST(:payload AS jsonb))
    """)
    for start in range(0, len(chunks), _CHUNK_BATCH):
        batch = chunks[start:start + _CHUNK_BATCH]
        session.execute(statement, [
            {
                "id": snapshot_id,
                "ordinal": start + offset,
                "payload": json.dumps(chunk, default=str),
            }
            for offset, chunk in enumerate(batch)
        ])
    # Only retire old cursors at publication; a failed build rolls it back.
    _lock_capacity(session)
    _retire_for_capacity(session, reserve=1)
    session.execute(text("""
        UPDATE transparency_page_snapshots
        SET summary = CAST(:summary AS jsonb),
            can_see_exemption_aggregates = :visible,
            item_count = :count,
            expires_at = now() + interval '20 minutes',
            ready = true
        WHERE id = :id
    """), {"id": snapshot_id, "summary": json.dumps(summary),
           "visible": can_see_exemption_aggregates, "count": len(rows)})


def read_slice(session: Session, snapshot_id: uuid.UUID, offset: int, limit: int) -> list[dict[str, Any]]:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if not 1 <= limit <= _ROWS_PER_CHUNK:
        raise ValueError(f"limit must be between 1 and {_ROWS_PER_CHUNK}")

    first_chunk = offset // _ROWS_PER_CHUNK
    last_chunk = (offset + limit - 1) // _ROWS_PER_CHUNK
    chunks = session.execute(text("""
        SELECT payload FROM transparency_page_snapshot_rows
        WHERE snapshot_id = :id AND ordinal BETWEEN :first AND :last
        ORDER BY ordinal LIMIT :chunk_count
    """), {
        "id": snapshot_id,
        "first": first_chunk,
        "last": last_chunk,
        "chunk_count": last_chunk - first_chunk + 1,
    }).scalars()
    flattened = [row for chunk in chunks for row in chunk]
    start_in_chunk = offset - first_chunk * _ROWS_PER_CHUNK
    return [dict(row) for row in flattened[start_in_chunk:start_in_chunk + limit]]


def discard_build(session: Session, snapshot_id: uuid.UUID) -> None:
    session.rollback()
    session.execute(text("DELETE FROM transparency_page_snapshots WHERE id = :id"), {"id": snapshot_id})
    session.commit()
