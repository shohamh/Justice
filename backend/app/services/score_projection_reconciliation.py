from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text, tuple_
from sqlalchemy.orm import Session

from app.db.models import (
    ScoreProjectionDirtyBucket,
    ScoreProjectionState,
)
from app.services.score_projection import (
    SCORE_PROJECTION_STATE_KEY,
    _canonical_bucket_summary,
    _json_safe_summary,
    _metadata_unprovable_bucket_keys,
    _persisted_bucket_summary,
    _upsert_quarter_total,
    _upsert_soldier_total,
    _utcnow,
    lock_partition_rows_for_keys,
    lock_score_projection_maintenance_shared,
    rebuild_projection_bucket,
)


def reconcile_score_projection(session: Session, limit: int = 500) -> dict[str, Any]:
    """Repair dirty score-projection buckets from canonical source rows.

    Normal write paths synchronously refresh their buckets. This routine is a
    safety net for any bucket that is nevertheless left dirty; it records whether
    persisted projection data diverged from canonical recomputation before repair.
    """
    dirty_rows = list(
        session.execute(
            select(ScoreProjectionDirtyBucket)
            .where(ScoreProjectionDirtyBucket.status == "dirty")
            .order_by(ScoreProjectionDirtyBucket.dirtied_at, ScoreProjectionDirtyBucket.id)
            .limit(limit)
        ).scalars()
    )
    candidate_keys = sorted(
        {(row.soldier_id, row.quarter_start) for row in dirty_rows},
        key=lambda item: (str(item[0]), item[1]),
    )
    if candidate_keys:
        lock_score_projection_maintenance_shared(session)
        dirty_rows = list(
            session.execute(
                select(ScoreProjectionDirtyBucket)
                .where(
                    tuple_(
                        ScoreProjectionDirtyBucket.soldier_id,
                        ScoreProjectionDirtyBucket.quarter_start,
                    ).in_(candidate_keys)
                )
                .order_by(
                    ScoreProjectionDirtyBucket.soldier_id,
                    ScoreProjectionDirtyBucket.quarter_start,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ).scalars()
        )
        dirty_rows = [row for row in dirty_rows if row.status == "dirty"]

    repair_keys = {(row.soldier_id, row.quarter_start) for row in dirty_rows}
    lock_partition_rows_for_keys(session, keys=repair_keys)

    repaired = 0
    diverged = 0
    repaired_soldiers: set[uuid.UUID] = set()
    repaired_quarters = set()
    for dirty in dirty_rows:
        before = _persisted_bucket_summary(
            session, soldier_id=dirty.soldier_id, quarter_start_value=dirty.quarter_start
        )
        expected = _canonical_bucket_summary(
            session, soldier_id=dirty.soldier_id, quarter_start_value=dirty.quarter_start
        )
        if _json_safe_summary(before) != _json_safe_summary(expected):
            dirty.divergence = {
                "before": _json_safe_summary(before),
                "expected": _json_safe_summary(expected),
            }
            diverged += 1
        rebuild_projection_bucket(
            session,
            dirty.soldier_id,
            dirty.quarter_start,
            refresh_soldier_total=False,
            refresh_quarter_total=False,
        )
        dirty.status = "current"
        dirty.reconciled_at = _utcnow()
        dirty.updated_at = _utcnow()
        repaired_soldiers.add(dirty.soldier_id)
        repaired_quarters.add(dirty.quarter_start)
        repaired += 1

    for soldier_id in sorted(repaired_soldiers, key=str):
        _upsert_soldier_total(session, soldier_id=soldier_id)
    for quarter_start_value in sorted(repaired_quarters):
        _upsert_quarter_total(session, quarter_start_value=quarter_start_value)

    session.flush()
    return {"checked": len(dirty_rows), "repaired": repaired, "diverged": diverged}


def revalidate_score_projection(
    session: Session, *, batch_size: int = 2000
) -> dict[str, Any]:
    """Fingerprint-proof one keyset batch of buckets and repair violations.

    Reads trust the writer invariant (a clean marker table means every stored
    bucket matches what its writer computed), so the per-row JSONB proof no
    longer runs on the read path. This routine is the periodic counterpart: it
    walks every bucket in deterministic keyset order, runs the proof against a
    bounded batch per call, rebuilds violating buckets from canonical rows, and
    advances a persistent cursor in ``score_projection_state`` so successive
    calls eventually cover the whole table before wrapping around.
    """
    state = session.get(ScoreProjectionState, SCORE_PROJECTION_STATE_KEY)
    if state is None or not state.backfill_complete:
        return {"validated": 0, "violations": 0, "repaired": 0}

    cursor_soldier_id = state.revalidated_after_soldier_id
    cursor_quarter_start = state.revalidated_after_quarter_start

    bucket_sql = text(
        """
        SELECT DISTINCT soldier_id, quarter_start
        FROM soldier_quarter_score_projection
        WHERE (CAST(:cursor_sid AS uuid) IS NULL AND CAST(:cursor_qs AS date) IS NULL)
           OR (soldier_id, quarter_start) > (CAST(:cursor_sid AS uuid), CAST(:cursor_qs AS date))
        """
    )
    buckets: list[tuple[uuid.UUID, Any]] = [
        (row[0], row[1])
        for row in session.execute(
            bucket_sql,
            {
                "cursor_sid": cursor_soldier_id,
                "cursor_qs": cursor_quarter_start,
                "batch_size": batch_size,
            },
        ).all()
    ]
    if not buckets:
        # Cycle complete — restart from the beginning next time.
        state.revalidated_after_soldier_id = None
        state.revalidated_after_quarter_start = None
        session.flush()
        return {"validated": 0, "violations": 0, "repaired": 0}

    keys = {(soldier_id, quarter_start_value) for soldier_id, quarter_start_value in buckets}
    violations = _metadata_unprovable_bucket_keys(session, keys=keys)

    repaired_quarters: set[Any] = set()
    for soldier_id, quarter_start_value in sorted(violations, key=lambda item: (str(item[0]), item[1])):
        rebuild_projection_bucket(session, soldier_id, quarter_start_value)
        repaired_quarters.add(quarter_start_value)
    for quarter_start_value in sorted(repaired_quarters):
        _upsert_quarter_total(session, quarter_start_value=quarter_start_value)

    last_soldier_id, last_quarter_start = buckets[-1]
    state.revalidated_after_soldier_id = last_soldier_id
    state.revalidated_after_quarter_start = last_quarter_start
    state.updated_at = _utcnow()
    session.flush()

    return {
        "validated": len(buckets),
        "violations": len(violations),
        "repaired": len(repaired_quarters),
    }
