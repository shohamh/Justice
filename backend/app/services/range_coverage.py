from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    RANGE_TYPE_RANK,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeEventStatus,
    RangeExcusalRequest,
    RangeExcusalStatus,
    SoldierRangeQualification,
)
from app.services.ranges import _validity_days


CoverageKind = Literal["qualification", "primary_range", "reserve_range", "none"]


@dataclass(frozen=True)
class RangeCoverage:
    qualified: bool
    coverage_kind: CoverageKind
    source_event_date: date | None
    valid_until: date | None


_NO_COVERAGE = RangeCoverage(
    qualified=False,
    coverage_kind="none",
    source_event_date=None,
    valid_until=None,
)


def _range_types_at_or_above(required_range_type: str) -> set[str]:
    required_rank = RANGE_TYPE_RANK[required_range_type]
    return {
        range_type
        for range_type, rank in RANGE_TYPE_RANK.items()
        if rank >= required_rank
    }


def _first_by_event_date(rows: Sequence[tuple]) -> tuple | None:
    return min(
        rows,
        key=lambda row: (row[1] is None, row[1] or date.max, row[2]),
        default=None,
    )


def _earliest_coverage(coverages: Sequence[RangeCoverage]) -> RangeCoverage:
    kind_tiebreaker = {
        "qualification": 0,
        "primary_range": 1,
        "reserve_range": 2,
    }
    return min(
        coverages,
        key=lambda coverage: (
            coverage.source_event_date is None,
            coverage.source_event_date or date.max,
            kind_tiebreaker[coverage.coverage_kind],
            coverage.valid_until or date.max,
        ),
    )


def get_range_coverages(
    session: Session,
    *,
    soldier_ids: Sequence[uuid.UUID],
    required_range_type: str,
    as_of: date,
) -> dict[uuid.UUID, RangeCoverage]:
    """Classify coverage for a candidate list with a bounded number of reads.

    The earliest applicable source is returned, with persisted qualification
    winning only same-date ties over primary and reserve coverage. A primary range
    is a projection, while reserve coverage requires recorded presence and never
    allows an event after ``as_of`` to qualify an earlier date.
    """
    unique_soldier_ids = set(soldier_ids)
    if not unique_soldier_ids:
        return {}

    candidate_types = _range_types_at_or_above(required_range_type)
    sources_by_soldier: dict[uuid.UUID, list[RangeCoverage]] = {
        soldier_id: [] for soldier_id in unique_soldier_ids
    }

    qualification_assignment = aliased(RangeAssignment)
    qualification_event = aliased(RangeEvent)
    qualification_rows = session.execute(
        select(
            SoldierRangeQualification.soldier_id,
            qualification_event.date,
            SoldierRangeQualification.valid_until,
        )
        .outerjoin(
            qualification_assignment,
            SoldierRangeQualification.source_range_assignment_id == qualification_assignment.id,
        )
        .outerjoin(
            qualification_event,
            SoldierRangeQualification.source_range_event_id == qualification_event.id,
        )
        .where(
            SoldierRangeQualification.soldier_id.in_(unique_soldier_ids),
            SoldierRangeQualification.range_type.in_(candidate_types),
            SoldierRangeQualification.valid_until >= as_of,
            or_(
                SoldierRangeQualification.source_range_assignment_id.is_(None),
                qualification_assignment.attendance_status == RangeAttendanceStatus.present,
            ),
        )
    ).all()
    qualifications_by_soldier: dict[uuid.UUID, list[tuple[uuid.UUID, date | None, date]]] = {}
    for row in qualification_rows:
        qualifications_by_soldier.setdefault(row.soldier_id, []).append(row)
    for soldier_id, rows in qualifications_by_soldier.items():
        _, source_event_date, valid_until = _first_by_event_date(rows)
        sources_by_soldier[soldier_id].append(
            RangeCoverage(
                qualified=True,
                coverage_kind="qualification",
                source_event_date=source_event_date,
                valid_until=valid_until,
            )
        )

    pending_excusal = exists(
        select(RangeExcusalRequest.id).where(
            RangeExcusalRequest.range_assignment_id == RangeAssignment.id,
            RangeExcusalRequest.status == RangeExcusalStatus.pending,
        )
    )
    primary_rows = session.execute(
        select(
            RangeAssignment.soldier_id,
            RangeEvent.date,
            RangeEvent.range_type,
        )
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id.in_(unique_soldier_ids),
            RangeAssignment.is_reserve.is_(False),
            RangeAssignment.is_draft.is_(False),
            RangeEvent.status == RangeEventStatus.planned,
            RangeEvent.date <= as_of,
            RangeEvent.range_type.in_(candidate_types),
            ~pending_excusal,
        )
    ).all()
    validity_days = {
        range_type: _validity_days(session, range_type)
        for range_type in {row.range_type for row in primary_rows}
    }
    primaries_by_soldier: dict[uuid.UUID, list[tuple[uuid.UUID, date, date]]] = {}
    for soldier_id, event_date, range_type in primary_rows:
        valid_until = event_date + timedelta(days=validity_days[range_type])
        if valid_until >= as_of:
            primaries_by_soldier.setdefault(soldier_id, []).append((soldier_id, event_date, valid_until))
    for soldier_id, rows in primaries_by_soldier.items():
        _, source_event_date, valid_until = _first_by_event_date(rows)
        sources_by_soldier[soldier_id].append(
            RangeCoverage(
                qualified=True,
                coverage_kind="primary_range",
                source_event_date=source_event_date,
                valid_until=valid_until,
            )
        )

    reserve_rows = session.execute(
        select(
            RangeAssignment.soldier_id,
            RangeEvent.date,
            RangeEvent.range_type,
        )
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id.in_(unique_soldier_ids),
            RangeAssignment.is_reserve.is_(True),
            RangeAssignment.is_draft.is_(False),
            RangeAssignment.attendance_status == RangeAttendanceStatus.present,
            RangeEvent.status != RangeEventStatus.cancelled,
            RangeEvent.date <= as_of,
            RangeEvent.range_type.in_(candidate_types),
        )
    ).all()
    validity_days.update({
        range_type: _validity_days(session, range_type)
        for range_type in {row.range_type for row in reserve_rows} - validity_days.keys()
    })
    reserves_by_soldier: dict[uuid.UUID, list[tuple[uuid.UUID, date, date]]] = {}
    for soldier_id, event_date, range_type in reserve_rows:
        valid_until = event_date + timedelta(days=validity_days[range_type])
        if valid_until >= as_of:
            reserves_by_soldier.setdefault(soldier_id, []).append((soldier_id, event_date, valid_until))
    for soldier_id, rows in reserves_by_soldier.items():
        _, source_event_date, valid_until = _first_by_event_date(rows)
        sources_by_soldier[soldier_id].append(
            RangeCoverage(
                qualified=True,
                coverage_kind="reserve_range",
                source_event_date=source_event_date,
                valid_until=valid_until,
            )
        )

    return {
        soldier_id: _earliest_coverage(sources) if sources else _NO_COVERAGE
        for soldier_id, sources in sources_by_soldier.items()
    }


def get_range_coverage(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    required_range_type: str,
    as_of: date,
) -> RangeCoverage:
    return get_range_coverages(
        session,
        soldier_ids=[soldier_id],
        required_range_type=required_range_type,
        as_of=as_of,
    )[soldier_id]
