from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyDayOverride, ScoreAdjustment
from app.services.effort_score import quarter_end, quarter_start
from app.services.scoring import _duty_type_scores, _effective_duty_day_rows


@dataclass(frozen=True)
class ProjectionBucket:
    soldier_id: uuid.UUID
    quarter_start: date
    duty_score: Decimal
    adjustment_score: Decimal
    shift_count: int
    source_fingerprint: dict[str, Any]


def _quarter_datetime_bounds(quarter_start_value: date) -> tuple[datetime, datetime]:
    start_at = datetime.combine(quarter_start_value, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(
        quarter_end(quarter_start_value) + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    return start_at, end_at


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
            "effective_soldier_id": row["effective_soldier_id"],
            "weighted_multiplier": row["weighted_multiplier"],
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


def _fingerprint_adjustments(adjustments: list[ScoreAdjustment]) -> list[dict[str, Any]]:
    return [
        {
            "adjustment_id": adjustment.id,
            "delta": adjustment.delta,
            "created_at": adjustment.created_at,
        }
        for adjustment in sorted(adjustments, key=lambda entry: (entry.created_at, str(entry.id)))
    ]


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
        source_fingerprint={
            "duty_rows": _fingerprint_duty_rows(duty_rows, type_scores),
            "adjustments": _fingerprint_adjustments(adjustments),
        },
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
