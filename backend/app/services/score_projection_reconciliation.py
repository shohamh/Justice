from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ScoreProjectionDirtyBucket
from app.services.score_projection import (
    _canonical_bucket_summary,
    _json_safe_summary,
    _persisted_bucket_summary,
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
