from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    ScoreAdjustment,
    ScoreProjectionQuarterTotal,
    ScoreProjectionState,
    Soldier,
    SoldierQuarterScoreProjection,
    SoldierScoreProjection,
)
from app.services.effort_score import quarter_end, quarter_start
from app.services.scoring import _duty_type_scores, _effective_duty_day_rows

SCORE_PROJECTION_CANONICAL_VERSION = "1"
SCORE_PROJECTION_STATE_KEY = "score_projection"


@dataclass(frozen=True)
class ProjectionBucket:
    soldier_id: uuid.UUID
    quarter_start: date
    duty_score: Decimal
    adjustment_score: Decimal
    shift_count: int
    source_fingerprint: dict[str, Any]


@dataclass(frozen=True)
class ProjectionTotals:
    duty_score: Decimal
    adjustment_score: Decimal
    total_score: Decimal
    shift_count: int


def _quarter_datetime_bounds(quarter_start_value: date) -> tuple[datetime, datetime]:
    start_at = datetime.combine(quarter_start_value, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(
        quarter_end(quarter_start_value) + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    return start_at, end_at


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(child) for child in value]
    return value


def _candidate_assignment_ids_for_bucket(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date
) -> set[uuid.UUID]:
    quarter_end_value = quarter_end(quarter_start_value)
    owned_ids = set(
        session.execute(
            select(DutyAssignment.id).where(
                DutyAssignment.status == "published",
                DutyAssignment.soldier_id == soldier_id,
                DutyAssignment.start_date <= quarter_end_value,
                DutyAssignment.end_date > quarter_start_value,
            )
        ).scalars().all()
    )
    override_ids = set(
        session.execute(
            select(DutyDayOverride.duty_assignment_id)
            .join(DutyAssignment, DutyAssignment.id == DutyDayOverride.duty_assignment_id)
            .where(
                DutyAssignment.status == "published",
                DutyDayOverride.effective_soldier_id == soldier_id,
                DutyDayOverride.date >= quarter_start_value,
                DutyDayOverride.date <= quarter_end_value,
            )
        ).scalars().all()
    )
    return owned_ids | override_ids


def _adjustments_for_bucket(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date
) -> list[ScoreAdjustment]:
    start_at, end_at = _quarter_datetime_bounds(quarter_start_value)
    return list(
        session.execute(
            select(ScoreAdjustment).where(
                ScoreAdjustment.soldier_id == soldier_id,
                ScoreAdjustment.created_at >= start_at,
                ScoreAdjustment.created_at < end_at,
            )
        ).scalars().all()
    )


def _fingerprint_duty_rows(
    duty_rows: list[dict[str, Any]], type_scores: dict[uuid.UUID, Decimal]
) -> list[dict[str, Any]]:
    return [
        {
            "assignment_id": row["assignment_id"],
            "day": row["day"],
            "duty_type_id": row["duty_type_id"],
            "assignment_soldier_id": row["assignment_soldier_id"],
            "effective_soldier_id": row["effective_soldier_id"],
            "day_weight": row["day_weight"],
            "multiplier": row["multiplier"],
            "multiplier_source": row["multiplier_source"],
            "weighted_multiplier": row["weighted_multiplier"],
            "override_id": row["override_id"],
            "override_date": row["override_date"],
            "override_effective_soldier_id": row["override_effective_soldier_id"],
            "override_reason": row["override_reason"],
            "dismissal_id": row["dismissal_id"],
            "dismissed_from": row["dismissed_from"],
            "dismissed_to": row["dismissed_to"],
            "dismissal_reason": row["dismissal_reason"],
            "score": type_scores.get(row["duty_type_id"], Decimal("0")) * row["weighted_multiplier"],
        }
        for row in sorted(
            duty_rows,
            key=lambda entry: (
                str(entry["assignment_id"]),
                entry["day"],
                str(entry["effective_soldier_id"]),
            ),
        )
    ]


def _fingerprint_overrides(duty_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overrides = {
        row["override_id"]: {
            "override_id": row["override_id"],
            "override_date": row["override_date"],
            "override_effective_soldier_id": row["override_effective_soldier_id"],
            "override_reason": row["override_reason"],
        }
        for row in duty_rows
        if row["override_id"] is not None
    }
    return [overrides[key] for key in sorted(overrides, key=str)]


def _fingerprint_dismissals(duty_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dismissals = {
        row["dismissal_id"]: {
            "dismissal_id": row["dismissal_id"],
            "dismissed_from": row["dismissed_from"],
            "dismissed_to": row["dismissed_to"],
            "dismissal_reason": row["dismissal_reason"],
        }
        for row in duty_rows
        if row["dismissal_id"] is not None
    }
    return [dismissals[key] for key in sorted(dismissals, key=str)]


def _fingerprint_adjustments(adjustments: list[ScoreAdjustment]) -> list[dict[str, Any]]:
    return [
        {
            "adjustment_id": adjustment.id,
            "delta": adjustment.delta,
            "created_at": adjustment.created_at,
        }
        for adjustment in sorted(adjustments, key=lambda entry: (entry.created_at, str(entry.id)))
    ]


def _empty_fingerprint() -> dict[str, list[dict[str, Any]]]:
    return {
        "duty_rows": [],
        "overrides": [],
        "dismissals": [],
        "adjustments": [],
    }


def project_soldier_bucket(
    session: Session, soldier_id: uuid.UUID, quarter_start_value: date
) -> ProjectionBucket:
    assignment_ids = _candidate_assignment_ids_for_bucket(
        session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
    )
    quarter_end_value = quarter_end(quarter_start_value)
    type_scores = _duty_type_scores(session)
    duty_rows = [
        row
        for row in _effective_duty_day_rows(
            session,
            statuses=["published"],
            assignment_ids=assignment_ids,
            date_from=quarter_start_value,
            date_to=quarter_end_value,
        )
        if row["effective_soldier_id"] == soldier_id and quarter_start(row["day"]) == quarter_start_value
    ]
    duty_score = sum(
        (type_scores.get(row["duty_type_id"], Decimal("0")) * row["weighted_multiplier"])
        for row in duty_rows
    )
    adjustments = _adjustments_for_bucket(
        session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
    )
    adjustment_score = sum((adjustment.delta for adjustment in adjustments), Decimal("0"))
    shift_count = len({row["assignment_id"] for row in duty_rows})
    return ProjectionBucket(
        soldier_id=soldier_id,
        quarter_start=quarter_start_value,
        duty_score=duty_score,
        adjustment_score=adjustment_score,
        shift_count=shift_count,
        source_fingerprint=(
            {
                "duty_rows": _fingerprint_duty_rows(duty_rows, type_scores),
                "overrides": _fingerprint_overrides(duty_rows),
                "dismissals": _fingerprint_dismissals(duty_rows),
                "adjustments": _fingerprint_adjustments(adjustments),
            }
            if duty_rows or adjustments
            else _empty_fingerprint()
        ),
    )


def project_all_buckets(
    session: Session,
    soldier_ids: set[uuid.UUID] | None = None,
    quarter_starts: set[date] | None = None,
) -> list[ProjectionBucket]:
    soldier_filter = set(soldier_ids) if soldier_ids is not None else None
    quarter_filter = set(quarter_starts) if quarter_starts is not None else None

    if soldier_filter is not None and quarter_filter is not None:
        keys = {
            (soldier_id, quarter_start_value)
            for soldier_id in soldier_filter
            for quarter_start_value in quarter_filter
        }
    else:
        date_from = min(quarter_filter) if quarter_filter else None
        date_to = max(quarter_end(qs) for qs in quarter_filter) if quarter_filter else None
        keys: set[tuple[uuid.UUID, date]] = set()

        for row in _effective_duty_day_rows(
            session,
            statuses=["published"],
            date_from=date_from,
            date_to=date_to,
        ):
            effective_soldier_id = row["effective_soldier_id"]
            quarter_start_value = quarter_start(row["day"])
            if soldier_filter is not None and effective_soldier_id not in soldier_filter:
                continue
            if quarter_filter is not None and quarter_start_value not in quarter_filter:
                continue
            keys.add((effective_soldier_id, quarter_start_value))

        adjustments_query = select(ScoreAdjustment)
        if soldier_filter is not None:
            adjustments_query = adjustments_query.where(ScoreAdjustment.soldier_id.in_(soldier_filter))
        if quarter_filter is not None:
            start_at = datetime.combine(min(quarter_filter), time.min, tzinfo=timezone.utc)
            end_at = datetime.combine(
                max(quarter_end(qs) for qs in quarter_filter) + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )
            adjustments_query = adjustments_query.where(
                ScoreAdjustment.created_at >= start_at,
                ScoreAdjustment.created_at < end_at,
            )
        for adjustment in session.execute(adjustments_query).scalars().all():
            quarter_start_value = quarter_start(adjustment.created_at.date())
            if quarter_filter is not None and quarter_start_value not in quarter_filter:
                continue
            keys.add((adjustment.soldier_id, quarter_start_value))

    return [
        project_soldier_bucket(session, soldier_id, quarter_start_value)
        for soldier_id, quarter_start_value in sorted(keys, key=lambda entry: (str(entry[0]), entry[1]))
    ]


def _projection_totals_from_rows(
    rows: list[SoldierQuarterScoreProjection],
) -> ProjectionTotals:
    duty_score = sum((row.duty_score for row in rows), Decimal("0"))
    adjustment_score = sum((row.adjustment_score for row in rows), Decimal("0"))
    total_score = sum((row.total_score for row in rows), Decimal("0"))
    shift_assignment_ids = {
        duty_row["assignment_id"]
        for row in rows
        for duty_row in row.source_fingerprint.get("duty_rows", [])
    }
    return ProjectionTotals(
        duty_score=duty_score,
        adjustment_score=adjustment_score,
        total_score=total_score,
        shift_count=len(shift_assignment_ids),
    )


def _bucket_to_row(bucket: ProjectionBucket) -> SoldierQuarterScoreProjection:
    return SoldierQuarterScoreProjection(
        soldier_id=bucket.soldier_id,
        quarter_start=bucket.quarter_start,
        projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
        duty_score=bucket.duty_score,
        adjustment_score=bucket.adjustment_score,
        total_score=bucket.duty_score + bucket.adjustment_score,
        shift_count=bucket.shift_count,
        source_fingerprint=_json_safe_value(bucket.source_fingerprint),
    )


def _get_or_create_state(session: Session) -> ScoreProjectionState:
    state = session.get(ScoreProjectionState, SCORE_PROJECTION_STATE_KEY)
    if state is None:
        state = ScoreProjectionState(
            projection_key=SCORE_PROJECTION_STATE_KEY,
            canonical_version=SCORE_PROJECTION_CANONICAL_VERSION,
            backfill_complete=False,
            resume_after_soldier_id=None,
            completed_at=None,
        )
        session.add(state)
        session.flush()
        return state
    state.canonical_version = SCORE_PROJECTION_CANONICAL_VERSION
    return state


def _replace_bucket_row(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date, bucket: ProjectionBucket
) -> None:
    existing = session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier_id,
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value,
        )
    ).scalar_one_or_none()
    if existing is not None:
        session.delete(existing)
        session.flush()
    session.add(_bucket_to_row(bucket))
    session.flush()


def _rows_for_soldier(
    session: Session, *, soldier_id: uuid.UUID
) -> list[SoldierQuarterScoreProjection]:
    return list(
        session.execute(
            select(SoldierQuarterScoreProjection).where(
                SoldierQuarterScoreProjection.soldier_id == soldier_id
            )
        ).scalars().all()
    )


def _rows_for_quarter(
    session: Session, *, quarter_start_value: date
) -> list[SoldierQuarterScoreProjection]:
    return list(
        session.execute(
            select(SoldierQuarterScoreProjection).where(
                SoldierQuarterScoreProjection.quarter_start == quarter_start_value
            )
        ).scalars().all()
    )


def _upsert_soldier_total(session: Session, *, soldier_id: uuid.UUID) -> SoldierScoreProjection:
    rows = _rows_for_soldier(session, soldier_id=soldier_id)
    totals = _projection_totals_from_rows(rows)
    projection = session.get(SoldierScoreProjection, soldier_id)
    if projection is None:
        projection = SoldierScoreProjection(
            soldier_id=soldier_id,
            projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
            duty_score=totals.duty_score,
            adjustment_score=totals.adjustment_score,
            cumulative_score=totals.total_score,
            shift_count=totals.shift_count,
        )
        session.add(projection)
    else:
        projection.projection_version = SCORE_PROJECTION_CANONICAL_VERSION
        projection.duty_score = totals.duty_score
        projection.adjustment_score = totals.adjustment_score
        projection.cumulative_score = totals.total_score
        projection.shift_count = totals.shift_count
        projection.updated_at = _utcnow()
    session.flush()
    return projection


def _upsert_quarter_total(
    session: Session, *, quarter_start_value: date
) -> ScoreProjectionQuarterTotal:
    rows = _rows_for_quarter(session, quarter_start_value=quarter_start_value)
    totals = _projection_totals_from_rows(rows)
    projection = session.get(ScoreProjectionQuarterTotal, quarter_start_value)
    if projection is None:
        projection = ScoreProjectionQuarterTotal(
            quarter_start=quarter_start_value,
            projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
            duty_score=totals.duty_score,
            adjustment_score=totals.adjustment_score,
            total_score=totals.total_score,
        )
        session.add(projection)
    else:
        projection.projection_version = SCORE_PROJECTION_CANONICAL_VERSION
        projection.duty_score = totals.duty_score
        projection.adjustment_score = totals.adjustment_score
        projection.total_score = totals.total_score
        projection.updated_at = _utcnow()
    session.flush()
    return projection


def rebuild_projection_bucket(
    session: Session, soldier_id: uuid.UUID, quarter_start_value: date
) -> SoldierQuarterScoreProjection:
    _get_or_create_state(session)
    bucket = project_soldier_bucket(session, soldier_id, quarter_start_value)
    _replace_bucket_row(
        session,
        soldier_id=soldier_id,
        quarter_start_value=quarter_start_value,
        bucket=bucket,
    )
    persisted = _quarter_row(
        session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
    )
    _upsert_soldier_total(session, soldier_id=soldier_id)
    _upsert_quarter_total(session, quarter_start_value=quarter_start_value)
    return persisted


def _quarter_row(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date
) -> SoldierQuarterScoreProjection:
    return session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier_id,
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value,
        )
    ).scalar_one()


def backfill_score_projection(
    session: Session,
    batch_size: int = 500,
    resume_after: uuid.UUID | None = None,
) -> ScoreProjectionState:
    state = _get_or_create_state(session)
    soldier_query = select(Soldier.id).order_by(Soldier.id)
    if resume_after is not None:
        soldier_query = soldier_query.where(Soldier.id > resume_after)
    soldier_ids = list(session.execute(soldier_query.limit(batch_size)).scalars().all())

    if not soldier_ids:
        state.backfill_complete = True
        state.resume_after_soldier_id = None
        state.completed_at = _utcnow()
        state.updated_at = _utcnow()
        session.flush()
        return state

    existing_quarters = {
        row.quarter_start
        for row in session.execute(
            select(SoldierQuarterScoreProjection).where(
                SoldierQuarterScoreProjection.soldier_id.in_(soldier_ids)
            )
        ).scalars().all()
    }
    for row in session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id.in_(soldier_ids)
        )
    ).scalars().all():
        session.delete(row)
    session.flush()

    buckets = project_all_buckets(session, soldier_ids=set(soldier_ids))
    for bucket in buckets:
        session.add(_bucket_to_row(bucket))
    session.flush()

    for soldier_id in soldier_ids:
        _upsert_soldier_total(session, soldier_id=soldier_id)

    affected_quarters = existing_quarters | {bucket.quarter_start for bucket in buckets}
    for quarter_start_value in sorted(affected_quarters):
        _upsert_quarter_total(session, quarter_start_value=quarter_start_value)

    last_processed = soldier_ids[-1]
    has_more = session.execute(
        select(Soldier.id).where(Soldier.id > last_processed).limit(1)
    ).scalar_one_or_none()
    state.backfill_complete = has_more is None
    state.resume_after_soldier_id = None if has_more is None else last_processed
    state.completed_at = _utcnow() if has_more is None else None
    state.updated_at = _utcnow()
    session.flush()
    return state
