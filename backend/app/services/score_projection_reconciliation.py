from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import (
    ScoreProjectionDirtyBucket,
    ScoreProjectionState,
    SoldierQuarterScoreProjection,
)
from app.services.score_projection import (
    SCORE_PROJECTION_CANONICAL_VERSION,
    SCORE_PROJECTION_STATE_KEY,
    _json_safe_summary,
    _canonical_bucket_summary,
    _metadata_unprovable_bucket_keys,
    _persisted_bucket_summary,
    _upsert_quarter_total,
    _utcnow,
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
    repaired = 0
    diverged = 0
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
        rebuild_projection_bucket(session, dirty.soldier_id, dirty.quarter_start)
        dirty.status = "current"
        dirty.reconciled_at = _utcnow()
        dirty.updated_at = _utcnow()
        repaired += 1
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
