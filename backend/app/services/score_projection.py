from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session
from app.services.sql_arrays import uuid_any

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyType,
    ScoreAdjustment,
    ScoreProjectionDirtyBucket,
    ScoreProjectionQuarterTotal,
    ScoreProjectionState,
    Soldier,
    SoldierQuarterScoreProjection,
    SoldierScoreProjection,
)
from app.services.effort_score import quarter_end, quarter_start
from app.services.scoring import _duty_type_scores, _effective_duty_day_rows

logger = logging.getLogger(__name__)

SCORE_PROJECTION_CANONICAL_VERSION = "1"
SCORE_PROJECTION_STATE_KEY = "score_projection"
SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY = "scoring.commander_dashboard_projection_reads_enabled"


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
    raw_day_count: int
    effective_weighted_days: Decimal
    duty_score: Decimal
    adjustment_score: Decimal
    total_score: Decimal
    shift_count: int


@dataclass(frozen=True)
class ProjectionPartitionRow:
    soldier_id: uuid.UUID
    quarter_start: date
    duty_type_id: uuid.UUID | None
    raw_day_count: int
    effective_weighted_days: Decimal
    duty_score: Decimal
    adjustment_score: Decimal
    source_fingerprint: dict[str, Any]


@dataclass(frozen=True)
class CommanderScoreReadDiagnostics:
    gate_enabled: bool
    used_projection: bool
    compared_soldiers: int
    matched_soldiers: int
    repaired_soldiers: int
    divergent_soldiers: int
    fallback_reason: str | None = None


@dataclass(frozen=True)
class CommanderScoreReadResult:
    score_by_soldier: dict[uuid.UUID, Decimal]
    diagnostics: CommanderScoreReadDiagnostics


def _quarter_datetime_bounds(quarter_start_value: date) -> tuple[datetime, datetime]:
    start_at = datetime.combine(quarter_start_value, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(
        quarter_end(quarter_start_value) + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    return start_at, end_at


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _q6(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"))


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


def _json_safe_summary(value: Any) -> Any:
    return _json_safe_value(value)


def _partition_sort_key(partition: tuple[uuid.UUID, date]) -> tuple[str, date]:
    return str(partition[0]), partition[1]


def _iter_quarters_touched(start_date: date, end_date: date) -> list[date]:
    if end_date <= start_date:
        return []
    touched: list[date] = []
    current = quarter_start(start_date)
    last_day = end_date - timedelta(days=1)
    last_quarter = quarter_start(last_day)
    while current <= last_quarter:
        touched.append(current)
        current = quarter_end(current) + timedelta(days=1)
    return touched


def _quarters_for_dates(affected_dates: set[date] | list[date] | tuple[date, ...]) -> set[date]:
    return {quarter_start(affected_date) for affected_date in affected_dates}


def affected_dates_for_assignment(assignment: DutyAssignment) -> set[date]:
    return set(_iter_quarters_touched(assignment.start_date, assignment.end_date))


def affected_dates_for_inclusive_period(start_date: date, end_date: date | None) -> set[date]:
    if end_date is None:
        return {start_date}
    if end_date < start_date:
        return set()
    return {start_date, end_date}


def affected_soldier_ids_for_assignment(session: Session, assignment: DutyAssignment) -> set[uuid.UUID]:
    soldier_ids = {assignment.soldier_id}
    soldier_ids.update(
        session.execute(
            select(DutyDayOverride.effective_soldier_id).where(
                DutyDayOverride.duty_assignment_id == assignment.id,
                DutyDayOverride.effective_soldier_id.is_not(None),
            )
        ).scalars().all()
    )
    return {soldier_id for soldier_id in soldier_ids if soldier_id is not None}


def affected_dates_for_soldier_existing_projection(session: Session, soldier_id: uuid.UUID) -> set[date]:
    affected_dates: set[date] = set()
    assignments = session.execute(
        select(DutyAssignment).where(DutyAssignment.soldier_id == soldier_id)
    ).scalars().all()
    for assignment in assignments:
        affected_dates.update(affected_dates_for_assignment(assignment))
    override_dates = session.execute(
        select(DutyDayOverride.date).where(DutyDayOverride.effective_soldier_id == soldier_id)
    ).scalars().all()
    affected_dates.update(override_dates)
    adjustment_dates = session.execute(
        select(ScoreAdjustment.created_at).where(ScoreAdjustment.soldier_id == soldier_id)
    ).scalars().all()
    affected_dates.update(created_at.date() for created_at in adjustment_dates if created_at is not None)
    persisted_quarters = session.execute(
        select(SoldierQuarterScoreProjection.quarter_start).where(
            SoldierQuarterScoreProjection.soldier_id == soldier_id
        )
    ).scalars().all()
    affected_dates.update(persisted_quarters)
    return affected_dates


def refresh_projection_for_assignment_change(
    session: Session,
    *,
    assignment: DutyAssignment,
    extra_soldier_ids: set[uuid.UUID] | list[uuid.UUID] | tuple[uuid.UUID, ...] = (),
) -> None:
    refresh_projection_for_change(
        session,
        soldier_ids=affected_soldier_ids_for_assignment(session, assignment) | set(extra_soldier_ids),
        affected_dates=affected_dates_for_assignment(assignment),
    )


def _merge_node_ids(existing: list[str] | None, incoming: tuple[uuid.UUID, ...] | list[uuid.UUID] | set[uuid.UUID]) -> list[str]:
    merged = set(existing or [])
    merged.update(str(node_id) for node_id in incoming if node_id is not None)
    return sorted(merged)


def _mark_dirty_bucket(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    quarter_start_value: date,
    old_node_ids: tuple[uuid.UUID, ...] | list[uuid.UUID] | set[uuid.UUID] = (),
    new_node_ids: tuple[uuid.UUID, ...] | list[uuid.UUID] | set[uuid.UUID] = (),
) -> ScoreProjectionDirtyBucket:
    dirty = session.execute(
        select(ScoreProjectionDirtyBucket).where(
            ScoreProjectionDirtyBucket.soldier_id == soldier_id,
            ScoreProjectionDirtyBucket.quarter_start == quarter_start_value,
        )
    ).scalar_one_or_none()
    if dirty is None:
        dirty = ScoreProjectionDirtyBucket(
            soldier_id=soldier_id,
            quarter_start=quarter_start_value,
            status="dirty",
            old_node_ids=[str(node_id) for node_id in old_node_ids],
            new_node_ids=[str(node_id) for node_id in new_node_ids],
            divergence=None,
        )
        session.add(dirty)
    else:
        dirty.status = "dirty"
        dirty.old_node_ids = _merge_node_ids(dirty.old_node_ids, old_node_ids)
        dirty.new_node_ids = _merge_node_ids(dirty.new_node_ids, new_node_ids)
        dirty.divergence = None
        dirty.updated_at = _utcnow()
    session.flush()
    return dirty


def _persisted_bucket_summary(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date
) -> dict[str, Any] | None:
    rows = list(
        session.execute(
            select(SoldierQuarterScoreProjection).where(
                SoldierQuarterScoreProjection.soldier_id == soldier_id,
                SoldierQuarterScoreProjection.quarter_start == quarter_start_value,
            )
        ).scalars().all()
    )
    if not rows:
        return None
    totals = _projection_totals_from_rows(rows)
    return {
        "raw_day_count": totals.raw_day_count,
        "effective_weighted_days": totals.effective_weighted_days,
        "duty_score": totals.duty_score,
        "adjustment_score": totals.adjustment_score,
        "total_score": totals.total_score,
        "shift_count": totals.shift_count,
        "fingerprints": [
            row.source_fingerprint
            for row in sorted(rows, key=lambda row: (row.duty_type_id is None, str(row.duty_type_id or "")))
        ],
    }


def _canonical_bucket_summary(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date
) -> dict[str, Any]:
    bucket = project_soldier_bucket(session, soldier_id, quarter_start_value)
    return {
        "raw_day_count": sum(row.raw_day_count for row in _bucket_partition_rows(bucket)),
        "effective_weighted_days": sum(
            (row.effective_weighted_days for row in _bucket_partition_rows(bucket)), Decimal("0")
        ).quantize(Decimal("0.000001")),
        "duty_score": bucket.duty_score.quantize(Decimal("0.000001")),
        "adjustment_score": bucket.adjustment_score.quantize(Decimal("0.000001")),
        "total_score": (bucket.duty_score + bucket.adjustment_score).quantize(Decimal("0.000001")),
        "shift_count": bucket.shift_count,
        "fingerprints": [
            _json_safe_value(row.source_fingerprint)
            for row in _bucket_partition_rows(bucket)
        ],
    }


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
        (
            type_scores.get(row["duty_type_id"], Decimal("0")) * row["weighted_multiplier"]
            for row in duty_rows
        ),
        Decimal("0"),
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
        for soldier_id, quarter_start_value in sorted(keys, key=_partition_sort_key)
    ]


def _bucket_partition_rows(bucket: ProjectionBucket) -> list[ProjectionPartitionRow]:
    duty_rows = bucket.source_fingerprint.get("duty_rows", [])
    grouped_rows: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for duty_row in duty_rows:
        grouped_rows[duty_row["duty_type_id"]].append(duty_row)

    overrides = {
        item["override_id"]: item
        for item in bucket.source_fingerprint.get("overrides", [])
        if item["override_id"] is not None
    }
    dismissals = {
        item["dismissal_id"]: item
        for item in bucket.source_fingerprint.get("dismissals", [])
        if item["dismissal_id"] is not None
    }

    rows: list[ProjectionPartitionRow] = []
    for duty_type_id in sorted(grouped_rows, key=str):
        typed_rows = grouped_rows[duty_type_id]
        override_ids = {row["override_id"] for row in typed_rows if row["override_id"] is not None}
        dismissal_ids = {row["dismissal_id"] for row in typed_rows if row["dismissal_id"] is not None}
        rows.append(
            ProjectionPartitionRow(
                soldier_id=bucket.soldier_id,
                quarter_start=bucket.quarter_start,
                duty_type_id=duty_type_id,
                raw_day_count=len(typed_rows),
                effective_weighted_days=sum(
                    (row["weighted_multiplier"] for row in typed_rows), Decimal("0")
                ),
                duty_score=sum((row["score"] for row in typed_rows), Decimal("0")),
                adjustment_score=Decimal("0"),
                source_fingerprint={
                    "duty_rows": typed_rows,
                    "overrides": [overrides[key] for key in sorted(override_ids, key=str)],
                    "dismissals": [dismissals[key] for key in sorted(dismissal_ids, key=str)],
                    "adjustments": [],
                },
            )
        )

    if bucket.adjustment_score != Decimal("0") or not duty_rows:
        rows.append(
            ProjectionPartitionRow(
                soldier_id=bucket.soldier_id,
                quarter_start=bucket.quarter_start,
                duty_type_id=None,
                raw_day_count=0,
                effective_weighted_days=Decimal("0"),
                duty_score=Decimal("0"),
                adjustment_score=bucket.adjustment_score,
                source_fingerprint={
                    "duty_rows": [],
                    "overrides": [],
                    "dismissals": [],
                    "adjustments": bucket.source_fingerprint.get("adjustments", []),
                },
            )
        )

    return rows


def _partition_row_model(row: ProjectionPartitionRow) -> SoldierQuarterScoreProjection:
    return SoldierQuarterScoreProjection(
        soldier_id=row.soldier_id,
        quarter_start=row.quarter_start,
        duty_type_id=row.duty_type_id,
        projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
        raw_day_count=row.raw_day_count,
        effective_weighted_days=row.effective_weighted_days.quantize(Decimal("0.000001")),
        duty_score=row.duty_score.quantize(Decimal("0.000001")),
        adjustment_score=row.adjustment_score.quantize(Decimal("0.000001")),
        source_fingerprint=_json_safe_value(row.source_fingerprint),
    )


def _projection_totals_from_rows(rows: list[SoldierQuarterScoreProjection]) -> ProjectionTotals:
    raw_day_count = sum(row.raw_day_count for row in rows)
    effective_weighted_days = sum((row.effective_weighted_days for row in rows), Decimal("0"))
    duty_score = sum((row.duty_score for row in rows), Decimal("0"))
    adjustment_score = sum((row.adjustment_score for row in rows), Decimal("0"))
    shift_assignment_ids = {
        duty_row["assignment_id"]
        for row in rows
        for duty_row in row.source_fingerprint.get("duty_rows", [])
    }
    return ProjectionTotals(
        raw_day_count=raw_day_count,
        effective_weighted_days=effective_weighted_days.quantize(Decimal("0.000001")),
        duty_score=duty_score.quantize(Decimal("0.000001")),
        adjustment_score=adjustment_score.quantize(Decimal("0.000001")),
        total_score=(duty_score + adjustment_score).quantize(Decimal("0.000001")),
        shift_count=len(shift_assignment_ids),
    )


def _projection_totals_from_buckets(buckets: list[ProjectionBucket]) -> ProjectionTotals:
    partition_rows = [row for bucket in buckets for row in _bucket_partition_rows(bucket)]
    duty_score = sum((bucket.duty_score for bucket in buckets), Decimal("0"))
    adjustment_score = sum((bucket.adjustment_score for bucket in buckets), Decimal("0"))
    return ProjectionTotals(
        raw_day_count=sum(row.raw_day_count for row in partition_rows),
        effective_weighted_days=sum(
            (row.effective_weighted_days for row in partition_rows), Decimal("0")
        ).quantize(Decimal("0.000001")),
        duty_score=duty_score.quantize(Decimal("0.000001")),
        adjustment_score=adjustment_score.quantize(Decimal("0.000001")),
        total_score=(duty_score + adjustment_score).quantize(Decimal("0.000001")),
        shift_count=sum(bucket.shift_count for bucket in buckets),
    )


def _bool_setting(session: Session, key: str, default: bool) -> bool:
    from app.services.settings_loader import SettingNotFound, get_setting

    try:
        value = get_setting(session, key)
    except SettingNotFound:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _get_or_create_state(session: Session) -> ScoreProjectionState:
    state = session.get(ScoreProjectionState, SCORE_PROJECTION_STATE_KEY)
    if state is None:
        state = ScoreProjectionState(
            projection_key=SCORE_PROJECTION_STATE_KEY,
            canonical_version=SCORE_PROJECTION_CANONICAL_VERSION,
            backfill_complete=False,
            resume_after_soldier_id=None,
            resume_after_quarter_start=None,
            completed_at=None,
        )
        session.add(state)
        session.flush()
        return state
    state.canonical_version = SCORE_PROJECTION_CANONICAL_VERSION
    return state


def _projection_state_is_complete(session: Session) -> bool:
    state = session.get(ScoreProjectionState, SCORE_PROJECTION_STATE_KEY)
    return (
        state is not None
        and state.backfill_complete is True
        and state.canonical_version == SCORE_PROJECTION_CANONICAL_VERSION
    )


def _state_resume_after(state: ScoreProjectionState) -> tuple[uuid.UUID, date] | None:
    if state.resume_after_soldier_id is None or state.resume_after_quarter_start is None:
        return None
    return (state.resume_after_soldier_id, state.resume_after_quarter_start)


def _delete_partition_rows(session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date) -> None:
    for row in session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier_id,
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value,
        )
    ).scalars().all():
        session.delete(row)
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
    want = _expected_soldier_totals_by_id(session, {soldier_id})[soldier_id]
    duty_score = _q6(want["duty_score"])
    adjustment_score = _q6(want["adjustment_score"])
    cumulative_score = _q6(duty_score + adjustment_score)
    shift_count = int(want["shift_count"])
    projection = session.get(SoldierScoreProjection, soldier_id)
    if projection is None:
        projection = SoldierScoreProjection(
            soldier_id=soldier_id,
            projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
            duty_score=duty_score,
            adjustment_score=adjustment_score,
            cumulative_score=cumulative_score,
            shift_count=shift_count,
        )
        session.add(projection)
    else:
        projection.projection_version = SCORE_PROJECTION_CANONICAL_VERSION
        projection.duty_score = duty_score
        projection.adjustment_score = adjustment_score
        projection.cumulative_score = cumulative_score
        projection.shift_count = shift_count
        projection.updated_at = _utcnow()
    session.flush()
    return projection


def _quarter_sums(session: Session, *, quarter_start_value: date) -> tuple[int, Any, Any, Any]:
    """Aggregate a quarter's partition rows server-side (no JSONB transfer)."""
    raw_sum, ewd_sum, duty_sum, adj_sum = session.execute(
        select(
            func.coalesce(func.sum(SoldierQuarterScoreProjection.raw_day_count), 0),
            func.coalesce(func.sum(SoldierQuarterScoreProjection.effective_weighted_days), 0),
            func.coalesce(func.sum(SoldierQuarterScoreProjection.duty_score), 0),
            func.coalesce(func.sum(SoldierQuarterScoreProjection.adjustment_score), 0),
        ).where(SoldierQuarterScoreProjection.quarter_start == quarter_start_value)
    ).one()
    return int(raw_sum), ewd_sum, duty_sum, adj_sum


def _upsert_quarter_total(
    session: Session, *, quarter_start_value: date
) -> ScoreProjectionQuarterTotal:
    raw_day_count, effective_weighted_days, duty_score, adjustment_score = _quarter_sums(
        session, quarter_start_value=quarter_start_value
    )
    total_score = Decimal(duty_score) + Decimal(adjustment_score)
    projection = session.get(ScoreProjectionQuarterTotal, quarter_start_value)
    if projection is None:
        projection = ScoreProjectionQuarterTotal(
            quarter_start=quarter_start_value,
            projection_version=SCORE_PROJECTION_CANONICAL_VERSION,
            raw_day_count=raw_day_count,
            effective_weighted_days=_q6(effective_weighted_days),
            duty_score=_q6(duty_score),
            adjustment_score=_q6(adjustment_score),
            total_score=_q6(total_score),
        )
        session.add(projection)
    else:
        projection.projection_version = SCORE_PROJECTION_CANONICAL_VERSION
        projection.raw_day_count = raw_day_count
        projection.effective_weighted_days = _q6(effective_weighted_days)
        projection.duty_score = _q6(duty_score)
        projection.adjustment_score = _q6(adjustment_score)
        projection.total_score = _q6(total_score)
        projection.updated_at = _utcnow()
    session.flush()
    return projection


def _projection_bucket_rows_are_complete(rows: list[SoldierQuarterScoreProjection]) -> bool:
    if not rows:
        return False
    aggregate_count = sum(1 for row in rows if row.duty_type_id is None)
    return aggregate_count <= 1 and all(
        row.projection_version == SCORE_PROJECTION_CANONICAL_VERSION for row in rows
    )


def _incomplete_bucket_keys(
    session: Session, keys: set[tuple[uuid.UUID, date]]
) -> set[tuple[uuid.UUID, date]]:
    """Keys with no partition rows, duplicate aggregate rows, or a stale version.

    Reads four light columns instead of hydrating full ORM entities with their
    JSONB fingerprints.
    """
    if not keys:
        return set()
    soldier_ids = {soldier_id for soldier_id, _quarter in keys}
    quarter_starts = {quarter_start_value for _soldier_id, quarter_start_value in keys}
    rows = session.execute(
        select(
            SoldierQuarterScoreProjection.soldier_id,
            SoldierQuarterScoreProjection.quarter_start,
            SoldierQuarterScoreProjection.duty_type_id,
            SoldierQuarterScoreProjection.projection_version,
        ).where(
            uuid_any("soldier_quarter_score_projection.soldier_id", soldier_ids),
            SoldierQuarterScoreProjection.quarter_start.in_(quarter_starts),
        )
    ).all()
    state: dict[tuple[uuid.UUID, date], dict[str, Any]] = {}
    for soldier_id, quarter_start_value, duty_type_id, projection_version in rows:
        key_state = state.setdefault(
            (soldier_id, quarter_start_value), {"aggregate": 0, "canonical": True}
        )
        if duty_type_id is None:
            key_state["aggregate"] += 1
        if projection_version != SCORE_PROJECTION_CANONICAL_VERSION:
            key_state["canonical"] = False
    return {
        key
        for key, key_state in state.items()
        if key_state["aggregate"] > 1 or not key_state["canonical"]
    } | (keys - set(state))


def _metadata_violation_clause() -> Any:
    """SQL predicate that is TRUE when a partition row's fingerprint proof fails.

    Mirrors scoring._projection_row_matches_fingerprint_metadata: each row must
    be consistent with its own source fingerprint. Runs inside PostgreSQL so
    the JSONB blobs are validated without shipping them to the client; callers
    only pay for the (normally empty) violating set.
    """
    return text(
        """
        NOT COALESCE(
            projection_version = :canonical_version
            AND (
                (
                    duty_type_id IS NULL
                    AND source_fingerprint -> 'duty_rows' = '[]'::jsonb
                    AND raw_day_count = 0
                    AND effective_weighted_days = 0
                    AND duty_score = 0
                    AND abs(
                        adjustment_score - COALESCE(
                            (SELECT SUM((a ->> 'delta')::numeric)
                             FROM jsonb_array_elements(
                                 COALESCE(source_fingerprint, '{}'::jsonb) -> 'adjustments'
                             ) a),
                            0
                        )
                    ) <= 0.0000005
                )
                OR (
                    duty_type_id IS NOT NULL
                    AND source_fingerprint -> 'adjustments' = '[]'::jsonb
                    AND adjustment_score = 0
                    AND raw_day_count = COALESCE(
                        (SELECT COUNT(*)
                         FROM jsonb_array_elements(
                             COALESCE(source_fingerprint, '{}'::jsonb) -> 'duty_rows'
                         ) d),
                        0
                    )
                    AND abs(
                        effective_weighted_days - COALESCE(
                            (SELECT SUM((d ->> 'weighted_multiplier')::numeric)
                             FROM jsonb_array_elements(
                                 COALESCE(source_fingerprint, '{}'::jsonb) -> 'duty_rows'
                             ) d),
                            0
                        )
                    ) <= 0.0000005
                    AND abs(
                        duty_score - COALESCE(
                            (SELECT SUM((d ->> 'score')::numeric)
                             FROM jsonb_array_elements(
                                 COALESCE(source_fingerprint, '{}'::jsonb) -> 'duty_rows'
                             ) d),
                            0
                        )
                    ) <= 0.0000005
                    AND NOT EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(
                            COALESCE(source_fingerprint, '{}'::jsonb) -> 'duty_rows'
                        ) d
                        WHERE d ->> 'duty_type_id' IS DISTINCT FROM CAST(duty_type_id AS text)
                    )
                )
            )
        , false)
        """
    ).bindparams(canonical_version=SCORE_PROJECTION_CANONICAL_VERSION)


def _metadata_unprovable_bucket_keys(
    session: Session,
    *,
    keys: set[tuple[uuid.UUID, date]] | None = None,
    soldier_ids: set[uuid.UUID] | None = None,
    quarter_starts: set[date] | None = None,
) -> set[tuple[uuid.UUID, date]]:
    if keys is not None:
        if not keys:
            return set()
        soldier_ids = {soldier_id for soldier_id, _quarter in keys}
        quarter_starts = {quarter_start_value for _soldier_id, quarter_start_value in keys}
    if not soldier_ids and not quarter_starts:
        return set()
    stmt = select(
        SoldierQuarterScoreProjection.soldier_id,
        SoldierQuarterScoreProjection.quarter_start,
    ).where(_metadata_violation_clause())
    if soldier_ids:
        stmt = stmt.where(uuid_any("soldier_quarter_score_projection.soldier_id", soldier_ids))
    if quarter_starts:
        stmt = stmt.where(SoldierQuarterScoreProjection.quarter_start.in_(quarter_starts))
    found = {(sid, qs) for sid, qs in session.execute(stmt).all()}
    if keys is not None:
        found &= keys
    return found


def _expected_soldier_totals_by_id(
    session: Session, soldier_ids: set[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Recompute every soldier's expected total from partition rows in bulk.

    Runs as a single server-side aggregate (the shift count needs a distinct
    over the JSONB fingerprint duty rows) so the fingerprints never leave the
    database.
    """
    if not soldier_ids:
        return {}
    id_params = sorted(str(soldier_id) for soldier_id in soldier_ids)
    rows = session.execute(
        text(
            """
            SELECT p.soldier_id AS soldier_id,
                   COALESCE(SUM(p.raw_day_count), 0) AS raw_day_count,
                   COALESCE(SUM(p.effective_weighted_days), 0) AS effective_weighted_days,
                   COALESCE(SUM(p.duty_score), 0) AS duty_score,
                   COALESCE(SUM(p.adjustment_score), 0) AS adjustment_score,
                   COALESCE((
                       SELECT COUNT(DISTINCT d ->> 'assignment_id')
                       FROM soldier_quarter_score_projection p2
                       CROSS JOIN LATERAL jsonb_array_elements(
                           COALESCE(p2.source_fingerprint, '{}'::jsonb) -> 'duty_rows'
                       ) d
                       WHERE p2.soldier_id = p.soldier_id
                   ), 0) AS shift_count
            FROM soldier_quarter_score_projection p
            WHERE p.soldier_id = ANY(CAST(:soldier_ids AS uuid[]))
            GROUP BY p.soldier_id
            """
        ).bindparams(soldier_ids=id_params)
    ).all()
    expected: dict[uuid.UUID, dict[str, Any]] = {}
    for soldier_id, raw_sum, ewd_sum, duty_sum, adj_sum, shift_count in rows:
        expected[uuid.UUID(str(soldier_id))] = {
            "raw_day_count": int(raw_sum),
            "effective_weighted_days": Decimal(str(ewd_sum)),
            "duty_score": Decimal(str(duty_sum)),
            "adjustment_score": Decimal(str(adj_sum)),
            "shift_count": int(shift_count),
        }
    for soldier_id in soldier_ids:
        expected.setdefault(
            soldier_id,
            {
                "raw_day_count": 0,
                "effective_weighted_days": Decimal("0"),
                "duty_score": Decimal("0"),
                "adjustment_score": Decimal("0"),
                "shift_count": 0,
            },
        )
    return expected


def _projection_keys_for_soldiers(
    session: Session, soldier_ids: set[uuid.UUID]
) -> set[tuple[uuid.UUID, date]]:
    """Persisted (soldier, quarter) buckets for the given soldiers.

    Read-path trust model: every mutation that affects scores rebuilds its
    buckets synchronously through ``refresh_projection_for_change``, so the
    persisted bucket set is exactly the set of buckets reads may need. The old
    implementation re-derived keys from every published assignment/override/
    adjustment, which scanned hundreds of thousands of rows per request.
    """
    if not soldier_ids:
        return set()

    id_params = sorted(str(soldier_id) for soldier_id in soldier_ids)
    rows = session.execute(
        text(
            """
            SELECT DISTINCT soldier_id, quarter_start
            FROM soldier_quarter_score_projection
            WHERE soldier_id = ANY(CAST(:ids AS uuid[]))
            """
        ).bindparams(ids=id_params)
    ).all()
    return {
        (row.soldier_id if isinstance(row.soldier_id, uuid.UUID) else uuid.UUID(str(row.soldier_id)), row.quarter_start)
        for row in rows
    }


def _bucket_health_counts(session: Session, *, soldier_ids: set[uuid.UUID]) -> tuple[int, int]:
    """One-row health summary: (duplicate-aggregate-groups, stale-version rows).

    Index-only against the covering index; lets reads skip detailed checks when
    everything is healthy.
    """
    if not soldier_ids:
        return (0, 0)
    id_params = sorted(str(soldier_id) for soldier_id in soldier_ids)
    row = session.execute(
        text(
            """
            SELECT COALESCE(SUM(g.agg_dup), 0), COALESCE(SUM(g.stale_rows), 0)
            FROM (
                SELECT soldier_id, quarter_start,
                       GREATEST(COUNT(*) FILTER (WHERE duty_type_id IS NULL) - 1, 0) AS agg_dup,
                       COUNT(*) FILTER (WHERE projection_version <> :canonical_version) AS stale_rows
                FROM soldier_quarter_score_projection
                WHERE soldier_id = ANY(CAST(:ids AS uuid[]))
                GROUP BY soldier_id, quarter_start
            ) g
            """
        ).bindparams(ids=id_params, canonical_version=SCORE_PROJECTION_CANONICAL_VERSION)
    ).one()
    return int(row[0]), int(row[1])


def _dirty_markers_present(session: Session, *, soldier_ids: set[uuid.UUID]) -> bool:
    if not soldier_ids:
        return False
    row = session.execute(
        select(ScoreProjectionDirtyBucket.id).where(
            uuid_any("score_projection_dirty_buckets.soldier_id", soldier_ids),
            ScoreProjectionDirtyBucket.status == "dirty",
        ).limit(1)
    ).first()
    return row is not None


def _unhealthy_bucket_keys_detailed(
    session: Session, *, soldier_ids: set[uuid.UUID]
) -> set[tuple[uuid.UUID, date]]:
    """The specific buckets failing completeness (rare; detailed fallback)."""
    if not soldier_ids:
        return set()
    id_params = sorted(str(soldier_id) for soldier_id in soldier_ids)
    rows = session.execute(
        text(
            """
            SELECT soldier_id, quarter_start
            FROM soldier_quarter_score_projection
            WHERE soldier_id = ANY(CAST(:ids AS uuid[]))
            GROUP BY soldier_id, quarter_start
            HAVING COUNT(*) FILTER (WHERE duty_type_id IS NULL) > 1
                OR BOOL_OR(projection_version <> :canonical_version)
            """
        ).bindparams(ids=id_params, canonical_version=SCORE_PROJECTION_CANONICAL_VERSION)
    ).all()
    return {
        (row[0] if isinstance(row[0], uuid.UUID) else uuid.UUID(str(row[0])), row[1])
        for row in rows
    }


def _dirty_or_divergent_projection_keys(
    session: Session,
    *,
    keys: set[tuple[uuid.UUID, date]] | None = None,
    soldier_ids: set[uuid.UUID] | None = None,
) -> set[tuple[uuid.UUID, date]]:
    """Buckets whose markers implicate them as needing repair.

    Reconciled divergences (recorded audit trail) are excluded — they describe
    past repairs, not pending work.
    """
    if keys is not None:
        if not keys:
            return set()
        soldier_ids = {soldier_id for soldier_id, _quarter in keys}
        quarter_starts = {quarter_start_value for _soldier_id, quarter_start_value in keys}
    elif not soldier_ids:
        return set()
    conditions = [
        or_(
            ScoreProjectionDirtyBucket.status == "dirty",
            and_(
                ScoreProjectionDirtyBucket.divergence.is_not(None),
                ScoreProjectionDirtyBucket.reconciled_at.is_(None),
            ),
        )
    ]
    if keys is not None:
        conditions.append(ScoreProjectionDirtyBucket.quarter_start.in_(quarter_starts))
    rows = session.execute(
        select(ScoreProjectionDirtyBucket).where(
            uuid_any("score_projection_dirty_buckets.soldier_id", soldier_ids),
            *conditions,
        )
    ).scalars().all()
    return {(row.soldier_id, row.quarter_start) for row in rows}


def _mark_projection_key_current(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date
) -> None:
    dirty = session.execute(
        select(ScoreProjectionDirtyBucket).where(
            ScoreProjectionDirtyBucket.soldier_id == soldier_id,
            ScoreProjectionDirtyBucket.quarter_start == quarter_start_value,
        )
    ).scalar_one_or_none()
    if dirty is None:
        return
    dirty.status = "current"
    dirty.divergence = None
    dirty.refreshed_at = _utcnow()
    dirty.updated_at = _utcnow()
    session.flush()


def _repair_projection_keys(
    session: Session, *, keys: set[tuple[uuid.UUID, date]]
) -> set[uuid.UUID]:
    repaired_soldiers: set[uuid.UUID] = set()
    repaired_quarters: set[date] = set()
    for soldier_id, quarter_start_value in sorted(keys, key=_partition_sort_key):
        rebuild_projection_bucket(
            session,
            soldier_id,
            quarter_start_value,
            refresh_quarter_total=False,
        )
        _mark_projection_key_current(
            session,
            soldier_id=soldier_id,
            quarter_start_value=quarter_start_value,
        )
        repaired_soldiers.add(soldier_id)
        repaired_quarters.add(quarter_start_value)
    for quarter_start_value in sorted(repaired_quarters):
        _upsert_quarter_total(session, quarter_start_value=quarter_start_value)
    return repaired_soldiers


def _repair_projection_for_soldiers(
    session: Session, *, soldier_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    if not soldier_ids:
        return set()
    keys = _projection_keys_for_soldiers(session, soldier_ids)
    repaired_soldiers = _repair_projection_keys(session, keys=keys)
    keyed_soldier_ids = {soldier_id for soldier_id, _quarter in keys}
    for soldier_id in sorted(soldier_ids - keyed_soldier_ids, key=str):
        _upsert_soldier_total(session, soldier_id=soldier_id)
        repaired_soldiers.add(soldier_id)
    return repaired_soldiers


def _aggregate_commander_score_totals(
    session: Session, *, soldier_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    if not soldier_ids:
        return {}

    duty_scores = (
        select(
            DutyAssignment.soldier_id.label("soldier_id"),
            func.sum(
                (DutyAssignment.end_date - DutyAssignment.start_date) * DutyType.score_per_day
            ).label("duty_score"),
        )
        .join(DutyType, DutyType.id == DutyAssignment.duty_type_id)
        .where(
            DutyAssignment.status == "published",
            uuid_any("duty_assignments.soldier_id", soldier_ids),
        )
        .group_by(DutyAssignment.soldier_id)
        .subquery()
    )
    adjustment_scores = (
        select(
            ScoreAdjustment.soldier_id.label("soldier_id"),
            func.sum(ScoreAdjustment.delta).label("adjustment_score"),
        )
        .where(uuid_any("score_adjustments.soldier_id", soldier_ids))
        .group_by(ScoreAdjustment.soldier_id)
        .subquery()
    )
    rows = session.execute(
        select(
            Soldier.id,
            duty_scores.c.duty_score,
            adjustment_scores.c.adjustment_score,
        )
        .select_from(Soldier)
        .outerjoin(duty_scores, duty_scores.c.soldier_id == Soldier.id)
        .outerjoin(adjustment_scores, adjustment_scores.c.soldier_id == Soldier.id)
        .where(uuid_any("soldiers.id", soldier_ids))
    ).all()
    return {
        soldier_id: _q6(Decimal(duty_score or 0) + Decimal(adjustment_score or 0))
        for soldier_id, duty_score, adjustment_score in rows
    }


def _canonical_commander_score_totals(
    session: Session, *, soldier_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    from app.services.scoring import _duty_stats_by_soldier, adjustments_by_soldier

    duty_scores, _shift_counts = _duty_stats_by_soldier(session)
    adjustment_scores = adjustments_by_soldier(session)
    return {
        soldier_id: _q6(
            duty_scores.get(soldier_id, Decimal("0"))
            + adjustment_scores.get(soldier_id, Decimal("0"))
        )
        for soldier_id in soldier_ids
    }


def _projected_commander_score_totals(
    session: Session, *, soldier_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Decimal]:
    if not soldier_ids:
        return {}
    rows = session.execute(
        select(SoldierScoreProjection).where(uuid_any("soldier_score_projection.soldier_id", soldier_ids))
    ).scalars().all()
    return {
        row.soldier_id: _q6(row.cumulative_score)
        for row in rows
        if row.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
    }


def _mismatched_commander_score_ids(
    *,
    soldier_ids: set[uuid.UUID],
    projected_scores: dict[uuid.UUID, Decimal],
    comparison_scores: dict[uuid.UUID, Decimal],
) -> set[uuid.UUID]:
    return {
        soldier_id
        for soldier_id in soldier_ids
        if _q6(projected_scores.get(soldier_id, Decimal("0")))
        != _q6(comparison_scores.get(soldier_id, Decimal("0")))
    }


def _commander_score_read_result(
    *,
    score_by_soldier: dict[uuid.UUID, Decimal],
    gate_enabled: bool,
    used_projection: bool,
    compared_soldiers: int,
    matched_soldiers: int,
    repaired_soldiers: int,
    divergent_soldiers: int,
    fallback_reason: str | None = None,
) -> CommanderScoreReadResult:
    return CommanderScoreReadResult(
        score_by_soldier={soldier_id: _q6(score) for soldier_id, score in score_by_soldier.items()},
        diagnostics=CommanderScoreReadDiagnostics(
            gate_enabled=gate_enabled,
            used_projection=used_projection,
            compared_soldiers=compared_soldiers,
            matched_soldiers=matched_soldiers,
            repaired_soldiers=repaired_soldiers,
            divergent_soldiers=divergent_soldiers,
            fallback_reason=fallback_reason,
        ),
    )


def rebuild_projection_bucket(
    session: Session,
    soldier_id: uuid.UUID,
    quarter_start_value: date,
    *,
    refresh_quarter_total: bool = True,
) -> list[SoldierQuarterScoreProjection]:
    _get_or_create_state(session)
    bucket = project_soldier_bucket(session, soldier_id, quarter_start_value)
    _delete_partition_rows(session, soldier_id=soldier_id, quarter_start_value=quarter_start_value)
    rows = [_partition_row_model(row) for row in _bucket_partition_rows(bucket)]
    session.add_all(rows)
    session.flush()
    _upsert_soldier_total(session, soldier_id=soldier_id)
    if refresh_quarter_total:
        _upsert_quarter_total(session, quarter_start_value=quarter_start_value)
    return rows


def refresh_projection_for_change(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID] | list[uuid.UUID] | tuple[uuid.UUID, ...],
    affected_dates: set[date] | list[date] | tuple[date, ...],
    old_node_ids: tuple[uuid.UUID, ...] | list[uuid.UUID] | set[uuid.UUID] = (),
    new_node_ids: tuple[uuid.UUID, ...] | list[uuid.UUID] | set[uuid.UUID] = (),
) -> None:
    """Synchronously refresh every affected soldier/quarter bucket.

    The dirty row is written before rebuilding and then marked current only after the
    bucket has been rebuilt from canonical rows. Reconciliation can therefore repair
    any bucket left dirty by a future interrupted writer, but normal writes do not
    rely on that safety net for freshness.
    """
    soldier_id_set = {soldier_id for soldier_id in soldier_ids if soldier_id is not None}
    quarter_starts = _quarters_for_dates(affected_dates)
    if not soldier_id_set or not quarter_starts:
        return

    for soldier_id in sorted(soldier_id_set, key=str):
        for quarter_start_value in sorted(quarter_starts):
            dirty = _mark_dirty_bucket(
                session,
                soldier_id=soldier_id,
                quarter_start_value=quarter_start_value,
                old_node_ids=old_node_ids,
                new_node_ids=new_node_ids,
            )
            rebuild_projection_bucket(session, soldier_id, quarter_start_value)
            dirty.status = "current"
            # A successful rebuild clears any recorded divergence; leaving it
            # set would make every subsequent read re-repair this bucket.
            dirty.divergence = None
            dirty.refreshed_at = _utcnow()
            dirty.updated_at = _utcnow()
            session.flush()


def _normalize_required_quarters(
    required_quarters: set[Any] | list[Any] | tuple[Any, ...],
) -> tuple[set[tuple[uuid.UUID, date]], set[date]]:
    bucket_keys: set[tuple[uuid.UUID, date]] = set()
    quarter_only: set[date] = set()
    for item in required_quarters:
        if isinstance(item, tuple) and len(item) == 2:
            soldier_id, quarter_start_value = item
            bucket_keys.add((soldier_id, quarter_start(quarter_start_value)))
        else:
            quarter_only.add(quarter_start(item))
    return bucket_keys, quarter_only


def projection_is_current(session: Session, required_quarters: set[Any] | list[Any] | tuple[Any, ...]) -> bool:
    bucket_keys, quarter_only = _normalize_required_quarters(required_quarters)
    if not bucket_keys and not quarter_only:
        return True

    dirty_query = select(ScoreProjectionDirtyBucket).where(
        ScoreProjectionDirtyBucket.status == "dirty"
    )
    if bucket_keys:
        dirty_rows = session.execute(dirty_query).scalars().all()
        if any((row.soldier_id, row.quarter_start) in bucket_keys for row in dirty_rows):
            return False
    if quarter_only:
        dirty_rows = session.execute(
            dirty_query.where(ScoreProjectionDirtyBucket.quarter_start.in_(quarter_only))
        ).scalars().all()
        if dirty_rows:
            return False
    return True


def _read_required_quarters(session: Session) -> set[date]:
    """Calendar quarters the projected transparency/effort reads validate totals for.

    Mirrors the window math used by scoring._try_projected_transparency_rows, so a
    completed backfill guarantees every quarter a read can demand — including
    empty history quarters between fairness.reset_date and the planning horizon —
    has a quarter-total row.
    """
    from app.services.scoring import (
        _effort_planning_start,
        _effort_quarter_windows,
        _effort_reset_date,
    )

    reset_date = _effort_reset_date(session)
    planning_start = _effort_planning_start(session)
    windows = _effort_quarter_windows(
        session,
        reset_date=reset_date,
        planning_start=planning_start,
        planning_end=planning_start,
    )
    return {calendar_quarter for _tracked_start, _tracked_end, calendar_quarter in windows}


def _ensure_read_required_quarter_totals(session: Session) -> None:
    existing = set(
        session.execute(select(ScoreProjectionQuarterTotal.quarter_start)).scalars().all()
    )
    for quarter_start_value in sorted(_read_required_quarters(session) - existing):
        _upsert_quarter_total(session, quarter_start_value=quarter_start_value)


def _enumerate_projection_keys(session: Session) -> list[tuple[uuid.UUID, date]]:
    keys: set[tuple[uuid.UUID, date]] = set()
    for assignment in session.execute(
        select(DutyAssignment).where(DutyAssignment.status == "published")
    ).scalars().all():
        for quarter_start_value in _iter_quarters_touched(assignment.start_date, assignment.end_date):
            keys.add((assignment.soldier_id, quarter_start_value))

    for override in session.execute(
        select(DutyDayOverride)
        .join(DutyAssignment, DutyAssignment.id == DutyDayOverride.duty_assignment_id)
        .where(
            DutyAssignment.status == "published",
            DutyDayOverride.effective_soldier_id.is_not(None),
        )
    ).scalars().all():
        if override.effective_soldier_id is not None:
            keys.add((override.effective_soldier_id, quarter_start(override.date)))

    for adjustment in session.execute(select(ScoreAdjustment)).scalars().all():
        keys.add((adjustment.soldier_id, quarter_start(adjustment.created_at.date())))

    return sorted(keys, key=_partition_sort_key)


def backfill_score_projection(
    session: Session,
    batch_size: int = 500,
    resume_after: tuple[uuid.UUID, date] | None = None,
) -> ScoreProjectionState:
    """Build/refresh all projection buckets, one calendar quarter per call.

    Each call rebuilds a whole quarter with the set-based bulk engine
    (`score_projection_bulk`), so query count is O(quarters), not O(buckets).
    ``batch_size`` is accepted for compatibility but quarter granularity
    supersedes it. The resume cursor advances per completed quarter.
    """
    from app.services.score_projection_bulk import (
        _bulk_upsert_soldier_totals,
        _rebuild_quarter_buckets_bulk,
    )

    state = _get_or_create_state(session)
    if resume_after is None and state.backfill_complete:
        session.flush()
        return state

    # Quarter-granular resume: `resume_after_quarter_start` records the last
    # completed quarter; that quarter and everything before it are skipped on
    # resume (re-processing a partially completed quarter is idempotent).
    completed_through = (
        resume_after[1] if resume_after is not None else state.resume_after_quarter_start
    )
    all_partitions = _enumerate_projection_keys(session)
    by_quarter: dict[date, list[tuple[uuid.UUID, date]]] = defaultdict(list)
    for partition in all_partitions:
        if completed_through is not None and partition[1] <= completed_through:
            continue
        by_quarter[partition[1]].append(partition)

    if not by_quarter:
        if not state.backfill_complete:
            _ensure_read_required_quarter_totals(session)
        state.backfill_complete = True
        state.resume_after_soldier_id = None
        state.resume_after_quarter_start = None
        state.completed_at = _utcnow()
        state.updated_at = _utcnow()
        session.flush()
        return state

    quarter = min(by_quarter)
    quarter_partitions = by_quarter[quarter]
    soldier_ids = {soldier_id for soldier_id, _quarter in quarter_partitions}

    _rebuild_quarter_buckets_bulk(
        session, quarter_start_value=quarter, soldier_ids=soldier_ids
    )
    _bulk_upsert_soldier_totals(session, soldier_ids)
    _upsert_quarter_total(session, quarter_start_value=quarter)

    has_more = any(q > quarter for q in by_quarter)
    last_partition = max(quarter_partitions, key=_partition_sort_key)
    state.backfill_complete = not has_more
    state.resume_after_soldier_id = last_partition[0] if has_more else None
    state.resume_after_quarter_start = quarter if has_more else None
    state.completed_at = _utcnow() if not has_more else None
    state.updated_at = _utcnow()
    if not has_more:
        _ensure_read_required_quarter_totals(session)
    session.flush()
    return state


def commander_score_totals(
    session: Session,
    *,
    soldiers: list[Soldier],
    canonical_diagnostic_compare: bool = False,
) -> CommanderScoreReadResult:
    soldier_ids = {soldier.id for soldier in soldiers}
    if not soldier_ids:
        return _commander_score_read_result(
            score_by_soldier={},
            gate_enabled=False,
            used_projection=False,
            compared_soldiers=0,
            matched_soldiers=0,
            repaired_soldiers=0,
            divergent_soldiers=0,
        )

    gate_enabled = _bool_setting(
        session,
        SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
        False,
    )
    if not gate_enabled:
        return _commander_score_read_result(
            score_by_soldier=_aggregate_commander_score_totals(session, soldier_ids=soldier_ids),
            gate_enabled=False,
            used_projection=False,
            compared_soldiers=0,
            matched_soldiers=0,
            repaired_soldiers=0,
            divergent_soldiers=0,
            fallback_reason="rollout_disabled",
        )

    if not _projection_state_is_complete(session):
        logger.warning(
            "commander dashboard score projection fell back because projection backfill is incomplete",
            extra={
                "gate_key": SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
                "soldier_count": len(soldier_ids),
                "fallback_reason": "projection_backfill_incomplete",
            },
        )
        return _commander_score_read_result(
            score_by_soldier=_canonical_commander_score_totals(session, soldier_ids=soldier_ids),
            gate_enabled=True,
            used_projection=False,
            compared_soldiers=0,
            matched_soldiers=0,
            repaired_soldiers=0,
            divergent_soldiers=0,
            fallback_reason="projection_backfill_incomplete",
        )

    keys = _projection_keys_for_soldiers(session, soldier_ids)
    repair_keys = _dirty_or_divergent_projection_keys(session, keys=keys)
    repair_keys.update(_incomplete_bucket_keys(session, keys))

    repaired_soldiers: set[uuid.UUID] = set()
    if repair_keys:
        try:
            repaired_soldiers.update(_repair_projection_keys(session, keys=repair_keys))
        except Exception:
            logger.exception(
                "commander dashboard score projection repair failed",
                extra={
                    "gate_key": SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
                    "soldier_count": len(soldier_ids),
                    "fallback_reason": "projection_repair_failed",
                },
            )
            return _commander_score_read_result(
                score_by_soldier=_canonical_commander_score_totals(session, soldier_ids=soldier_ids),
                gate_enabled=True,
                used_projection=False,
                compared_soldiers=0,
                matched_soldiers=0,
                repaired_soldiers=0,
                divergent_soldiers=0,
                fallback_reason="projection_repair_failed",
            )

    if keys and not projection_is_current(session, keys):
        logger.warning(
            "commander dashboard score projection fell back because required buckets are not current",
            extra={
                "gate_key": SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
                "soldier_count": len(soldier_ids),
                "fallback_reason": "projection_not_current",
            },
        )
        return _commander_score_read_result(
            score_by_soldier=_canonical_commander_score_totals(session, soldier_ids=soldier_ids),
            gate_enabled=True,
            used_projection=False,
            compared_soldiers=0,
            matched_soldiers=0,
            repaired_soldiers=len(repaired_soldiers),
            divergent_soldiers=0,
            fallback_reason="projection_not_current",
        )

    if _incomplete_bucket_keys(session, keys):
        logger.warning(
            "commander dashboard score projection fell back because required buckets are incomplete",
            extra={
                "gate_key": SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
                "soldier_count": len(soldier_ids),
                "fallback_reason": "projection_incomplete",
            },
        )
        return _commander_score_read_result(
            score_by_soldier=_canonical_commander_score_totals(session, soldier_ids=soldier_ids),
            gate_enabled=True,
            used_projection=False,
            compared_soldiers=0,
            matched_soldiers=0,
            repaired_soldiers=len(repaired_soldiers),
            divergent_soldiers=0,
            fallback_reason="projection_incomplete",
        )

    projected_scores = _projected_commander_score_totals(session, soldier_ids=soldier_ids)
    required_total_ids = {soldier_id for soldier_id, _quarter_start_value in keys}
    missing_total_ids = required_total_ids - set(projected_scores)
    if missing_total_ids:
        repaired_soldiers.update(_repair_projection_for_soldiers(session, soldier_ids=missing_total_ids))
        projected_scores = _projected_commander_score_totals(session, soldier_ids=soldier_ids)
        missing_total_ids = required_total_ids - set(projected_scores)
    if missing_total_ids:
        logger.warning(
            "commander dashboard score projection fell back because required totals are missing",
            extra={
                "gate_key": SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
                "soldier_count": len(soldier_ids),
                "fallback_reason": "projection_totals_missing",
            },
        )
        return _commander_score_read_result(
            score_by_soldier=_canonical_commander_score_totals(session, soldier_ids=soldier_ids),
            gate_enabled=True,
            used_projection=False,
            compared_soldiers=0,
            matched_soldiers=0,
            repaired_soldiers=len(repaired_soldiers),
            divergent_soldiers=0,
            fallback_reason="projection_totals_missing",
        )

    if canonical_diagnostic_compare:
        canonical_scores = _canonical_commander_score_totals(session, soldier_ids=soldier_ids)
        mismatched_ids = _mismatched_commander_score_ids(
            soldier_ids=soldier_ids,
            projected_scores=projected_scores,
            comparison_scores=canonical_scores,
        )
        if mismatched_ids:
            repaired_soldiers.update(_repair_projection_for_soldiers(session, soldier_ids=mismatched_ids))
            projected_scores = _projected_commander_score_totals(session, soldier_ids=soldier_ids)
            mismatched_ids = _mismatched_commander_score_ids(
                soldier_ids=soldier_ids,
                projected_scores=projected_scores,
                comparison_scores=canonical_scores,
            )
        if mismatched_ids:
            logger.warning(
                "commander dashboard score projection diagnostic comparison diverged",
                extra={
                    "gate_key": SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
                    "soldier_count": len(soldier_ids),
                    "compared_soldiers": len(soldier_ids),
                    "matched_soldiers": len(soldier_ids) - len(mismatched_ids),
                    "repaired_soldiers": len(repaired_soldiers),
                    "divergent_soldiers": len(mismatched_ids),
                },
            )
        else:
            logger.info(
                "commander dashboard score projection diagnostic comparison matched",
                extra={
                    "gate_key": SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
                    "soldier_count": len(soldier_ids),
                    "compared_soldiers": len(soldier_ids),
                    "matched_soldiers": len(soldier_ids),
                    "repaired_soldiers": len(repaired_soldiers),
                    "divergent_soldiers": 0,
                },
            )
        return _commander_score_read_result(
            score_by_soldier={
                soldier_id: projected_scores.get(soldier_id, Decimal("0"))
                for soldier_id in soldier_ids
            },
            gate_enabled=True,
            used_projection=True,
            compared_soldiers=len(soldier_ids),
            matched_soldiers=len(soldier_ids) - len(mismatched_ids),
            repaired_soldiers=len(repaired_soldiers),
            divergent_soldiers=len(mismatched_ids),
        )

    return _commander_score_read_result(
        score_by_soldier={
            soldier_id: projected_scores.get(soldier_id, Decimal("0"))
            for soldier_id in soldier_ids
        },
        gate_enabled=True,
        used_projection=True,
        compared_soldiers=0,
        matched_soldiers=0,
        repaired_soldiers=len(repaired_soldiers),
        divergent_soldiers=0,
    )


def reconcile_score_projection(session: Session, limit: int = 500) -> dict[str, Any]:
    from app.services.score_projection_reconciliation import reconcile_score_projection as _reconcile

    return _reconcile(session, limit=limit)
