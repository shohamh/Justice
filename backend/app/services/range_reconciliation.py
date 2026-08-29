from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import (
    RANGE_TYPE_RANK,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeEventStatus,
    RangeExcusalRequest,
    RangeExcusalStatus,
)
from app.services.ranges import _remove_range_assignment_in_transaction, _validity_days


@dataclass
class ReconciliationResult:
    removed_assignment_ids: list[uuid.UUID] = field(default_factory=list)
    refilled_primary_assignment_ids: list[uuid.UUID] = field(default_factory=list)
    refilled_reserve_assignment_ids: list[uuid.UUID] = field(default_factory=list)
    unfilled_primary_count: int = 0
    unfilled_reserve_count: int = 0


def _source_provides_guaranteed_coverage(
    session: Session, *, assignment: RangeAssignment, event: RangeEvent,
) -> bool:
    if assignment.is_draft:
        return False

    if assignment.is_reserve:
        return assignment.attendance_status == RangeAttendanceStatus.present and event.status != RangeEventStatus.cancelled

    if event.status != RangeEventStatus.planned:
        return False
    pending_excusal = session.execute(
        select(exists().where(
            RangeExcusalRequest.range_assignment_id == assignment.id,
            RangeExcusalRequest.status == RangeExcusalStatus.pending,
        ))
    ).scalar_one()
    return not pending_excusal


def reconcile_future_range_assignments(
    session: Session, *, soldier_id: uuid.UUID, source_event: RangeEvent,
    actor_id: uuid.UUID | None,
) -> ReconciliationResult:
    """Remove redundant later assignments without committing the transaction.

    The source assignment is the only coverage trigger. Future planned target
    events are visited in date order, and draft assignments are never touched.
    Refill fields remain empty until the follow-up implementation adds slot-
    preserving candidate selection.
    """
    result = ReconciliationResult()
    source_assignment = session.execute(
        select(RangeAssignment).where(
            RangeAssignment.range_event_id == source_event.id,
            RangeAssignment.soldier_id == soldier_id,
        )
    ).scalar_one_or_none()
    if source_assignment is None or not _source_provides_guaranteed_coverage(
        session, assignment=source_assignment, event=source_event,
    ):
        return result

    source_valid_until = source_event.date + timedelta(
        days=_validity_days(session, source_event.range_type),
    )
    targets = session.execute(
        select(RangeAssignment, RangeEvent)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier_id,
            RangeAssignment.range_event_id != source_event.id,
            RangeAssignment.is_draft.is_(False),
            RangeEvent.status == RangeEventStatus.planned,
            RangeEvent.date > source_event.date,
            RangeEvent.date <= source_valid_until,
            RangeEvent.range_type.in_(
                range_type for range_type, rank in RANGE_TYPE_RANK.items()
                if rank <= RANGE_TYPE_RANK[source_event.range_type]
            ),
        )
        .order_by(RangeEvent.date, RangeEvent.id)
    ).all()

    for assignment, _event in targets:
        _remove_range_assignment_in_transaction(
            session,
            assignment=assignment,
            reason="redundant_future_range_assignment",
            actor_id=actor_id,
        )
        result.removed_assignment_ids.append(assignment.id)

    return result
