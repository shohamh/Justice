"""Set-based bulk bucket rebuild for backfill.

Rebuilds every bucket of a quarter in a handful of queries instead of ~12
queries per bucket, while producing byte-identical partition rows: the same
`_effective_duty_day_rows` expansion, the same fingerprint builders, and the
same `_bucket_partition_rows` partitioning as the per-bucket path.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    ScoreAdjustment,
    SoldierQuarterScoreProjection,
)
from app.services.effort_score import quarter_end
from app.services.score_projection import (
    ProjectionBucket,
    _bucket_partition_rows,
    _duty_type_scores,
    _effective_duty_day_rows,
    _empty_fingerprint,
    _fingerprint_adjustments,
    _fingerprint_dismissals,
    _fingerprint_duty_rows,
    _fingerprint_overrides,
    _partition_row_model,
)


def _rebuild_quarter_buckets_bulk(
    session: Session, *, quarter_start_value: date, soldier_ids: set[uuid.UUID]
) -> int:
    """Rebuild every bucket of `quarter_start_value` for `soldier_ids`.

    Returns the number of buckets written. Deletes any other partition rows of
    the quarter for these soldiers (stale leftovers from earlier enumerations).
    """
    if not soldier_ids:
        return 0

    quarter_end_value = quarter_end(quarter_start_value)
    type_scores = _duty_type_scores(session)

    # Candidate detection mirrors _candidate_assignment_ids_for_bucket:
    # assignments owned by the soldier overlapping the quarter, plus
    # override-referenced buckets.
    assignment_rows = session.execute(
        select(DutyAssignment.id, DutyAssignment.soldier_id).where(
            DutyAssignment.status == "published",
            DutyAssignment.start_date <= quarter_end_value,
            DutyAssignment.end_date > quarter_start_value,
        )
    ).all()
    owned_by_soldier: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for assignment_id, owner_id in assignment_rows:
        owned_by_soldier[owner_id].add(assignment_id)

    from app.db.models import DutyDayOverride

    override_rows = session.execute(
        select(DutyDayOverride.duty_assignment_id, DutyDayOverride.effective_soldier_id)
        .join(DutyAssignment, DutyAssignment.id == DutyDayOverride.duty_assignment_id)
        .where(
            DutyAssignment.status == "published",
            DutyDayOverride.date >= quarter_start_value,
            DutyDayOverride.date <= quarter_end_value,
        )
    ).all()
    override_refs: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for duty_assignment_id, effective_soldier_id in override_rows:
        if effective_soldier_id is not None:
            override_refs[effective_soldier_id].add(duty_assignment_id)

    # One canonical expansion for the whole quarter.
    duty_rows = _effective_duty_day_rows(
        session, statuses=["published"], date_from=quarter_start_value, date_to=quarter_end_value
    )

    start_at = datetime.combine(quarter_start_value, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(quarter_end_value + timedelta(days=1), time.min, tzinfo=timezone.utc)
    adjustments = (
        session.execute(
            select(ScoreAdjustment).where(
                ScoreAdjustment.created_at >= start_at,
                ScoreAdjustment.created_at < end_at,
            )
        )
        .scalars()
        .all()
    )
    adjustments_by_soldier: dict[uuid.UUID, list[ScoreAdjustment]] = defaultdict(list)
    for adjustment in adjustments:
        adjustments_by_soldier[adjustment.soldier_id].append(adjustment)

    rows_by_soldier: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in duty_rows:
        effective_soldier_id = row["effective_soldier_id"]
        if effective_soldier_id in soldier_ids:
            rows_by_soldier[effective_soldier_id].append(row)

    buckets: list[ProjectionBucket] = []
    for soldier_id in sorted(soldier_ids):
        soldier_rows = rows_by_soldier.get(soldier_id, [])
        soldier_adjustments = adjustments_by_soldier.get(soldier_id, [])
        has_candidate = (
            bool(owned_by_soldier.get(soldier_id))
            or bool(override_refs.get(soldier_id))
            or bool(soldier_rows)
            or bool(soldier_adjustments)
        )
        if not has_candidate:
            continue
        duty_score = sum(
            (
                type_scores.get(row["duty_type_id"], Decimal("0")) * row["weighted_multiplier"]
                for row in soldier_rows
            ),
            Decimal("0"),
        )
        adjustment_score = sum((a.delta for a in soldier_adjustments), Decimal("0"))
        shift_count = len({row["assignment_id"] for row in soldier_rows})
        buckets.append(
            ProjectionBucket(
                soldier_id=soldier_id,
                quarter_start=quarter_start_value,
                duty_score=duty_score,
                adjustment_score=adjustment_score,
                shift_count=shift_count,
                source_fingerprint=(
                    {
                        "duty_rows": _fingerprint_duty_rows(soldier_rows, type_scores),
                        "overrides": _fingerprint_overrides(soldier_rows),
                        "dismissals": _fingerprint_dismissals(soldier_rows),
                        "adjustments": _fingerprint_adjustments(soldier_adjustments),
                    }
                    if soldier_rows or soldier_adjustments
                    else _empty_fingerprint()
                ),
            )
        )

    # Stale-row cleanup: drop every partition row of the quarter for these
    # soldiers, then insert the freshly computed ones.
    session.execute(
        SoldierQuarterScoreProjection.__table__.delete().where(
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value,
            SoldierQuarterScoreProjection.soldier_id.in_(soldier_ids),
        )
    )
    partition_models = [
        _partition_row_model(row) for bucket in buckets for row in _bucket_partition_rows(bucket)
    ]
    session.add_all(partition_models)
    session.flush()
    return len(buckets)


def _bulk_upsert_soldier_totals(session: Session, soldier_ids: set[uuid.UUID]) -> None:
    """Recompute soldier totals for the given soldiers in one statement."""
    if not soldier_ids:
        return
    from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION

    session.execute(
        text(
            """
            INSERT INTO soldier_score_projection AS s
                (soldier_id, projection_version, duty_score, adjustment_score,
                 cumulative_score, shift_count, updated_at)
            SELECT b.soldier_id,
                   :version,
                   ROUND(COALESCE(SUM(p.duty_score), 0), 6),
                   ROUND(COALESCE(SUM(p.adjustment_score), 0), 6),
                   ROUND(COALESCE(SUM(p.duty_score) + SUM(p.adjustment_score), 0), 6),
                   COALESCE((
                       SELECT COUNT(DISTINCT d ->> 'assignment_id')
                       FROM soldier_quarter_score_projection p2
                       CROSS JOIN LATERAL jsonb_array_elements(
                           COALESCE(p2.source_fingerprint, '{}'::jsonb) -> 'duty_rows'
                       ) d
                       WHERE p2.soldier_id = b.soldier_id
                   ), 0),
                   now()
            FROM unnest(CAST(:ids AS uuid[])) AS b(soldier_id)
            LEFT JOIN soldier_quarter_score_projection p ON p.soldier_id = b.soldier_id
            GROUP BY b.soldier_id
            ON CONFLICT (soldier_id) DO UPDATE SET
                projection_version = EXCLUDED.projection_version,
                duty_score = EXCLUDED.duty_score,
                adjustment_score = EXCLUDED.adjustment_score,
                cumulative_score = EXCLUDED.cumulative_score,
                shift_count = EXCLUDED.shift_count,
                updated_at = now()
            """
        ),
        {
            "version": SCORE_PROJECTION_CANONICAL_VERSION,
            "ids": sorted(str(soldier_id) for soldier_id in soldier_ids),
        },
    )
