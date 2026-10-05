"""PostgreSQL parity checks for chunked transparency snapshot rows."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import event, text


def test_chunked_snapshot_rows_preserve_exact_bounded_slices(admin_session):
    from app.services import transparency_page_store

    snapshot_id = uuid.uuid4()
    source_snapshot = admin_session.execute(
        text("SELECT pg_current_snapshot()::text")
    ).scalar_one()
    admin_session.execute(text("""
        INSERT INTO transparency_page_snapshots
          (id, binding, source_generation, source_snapshot, as_of, expires_at, ready)
        VALUES (:id, 'chunk-test', 1, :source_snapshot, :as_of,
                now() + interval '20 minutes', false)
    """), {
        "id": snapshot_id,
        "source_snapshot": source_snapshot,
        "as_of": date.today(),
    })
    rows = [
        {
            "row_num": index + 1,
            "soldier_id": f"soldier-{index + 1}",
            "full_name": f"Soldier {index + 1}",
        }
        for index in range(257)
    ]

    transparency_page_store.persist_rows(
        admin_session,
        snapshot_id,
        rows,
        {"row_count": len(rows)},
        True,
    )

    stored_chunks = admin_session.execute(text("""
        SELECT ordinal, payload
        FROM transparency_page_snapshot_rows
        WHERE snapshot_id = :id
        ORDER BY ordinal
    """), {"id": snapshot_id}).all()
    assert len(stored_chunks) == 3
    assert [ordinal for ordinal, _payload in stored_chunks] == [0, 1, 2]
    assert [len(payload) for _ordinal, payload in stored_chunks] == [100, 100, 57]

    for offset in (0, 99, 100):
        for page_size in (1, 30, 100):
            assert transparency_page_store.read_slice(
                    admin_session, snapshot_id, offset, page_size
                ) == rows[offset:offset + page_size]


def test_chunk_persistence_uses_one_transactional_executemany(admin_session, admin_engine):
    from app.services import transparency_page_store

    snapshot_id = uuid.uuid4()
    source_snapshot = admin_session.execute(
        text("SELECT pg_current_snapshot()::text")
    ).scalar_one()
    admin_session.execute(text("""
        INSERT INTO transparency_page_snapshots
          (id, binding, source_generation, source_snapshot, as_of, expires_at, ready)
        VALUES (:id, 'executemany-test', 1, :source_snapshot, :as_of,
                now() + interval '20 minutes', false)
    """), {
        "id": snapshot_id,
        "source_snapshot": source_snapshot,
        "as_of": date.today(),
    })
    rows = [
        {"row_num": index + 1, "soldier_id": f"soldier-{index + 1}"}
        for index in range(201)
    ]
    chunk_insert_calls = []

    def record_chunk_insert(_connection, _cursor, statement, _parameters, _context, executemany):
        if "INSERT INTO transparency_page_snapshot_rows" in statement:
            chunk_insert_calls.append(executemany)

    event.listen(admin_engine, "before_cursor_execute", record_chunk_insert)
    try:
        transparency_page_store.persist_rows(
            admin_session,
            snapshot_id,
            rows,
            {"row_count": len(rows)},
            True,
        )
    finally:
        event.remove(admin_engine, "before_cursor_execute", record_chunk_insert)

    assert chunk_insert_calls == [True]
    admin_session.rollback()
    with admin_engine.connect() as connection:
        assert connection.execute(text("""
            SELECT count(*) FROM transparency_page_snapshot_rows
            WHERE snapshot_id = :id
        """), {"id": snapshot_id}).scalar_one() == 0
