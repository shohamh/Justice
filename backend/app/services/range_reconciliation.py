from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    RANGE_TYPE_RANK,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeEventStatus,
    RangeExcusalRequest,
    RangeExcusalStatus,
)
from app.services.range_auto_assign import _earliest_future_weapon_duty_start, rank_candidates
from app.services.ranges import (
    RangeValidationError,
    _acquire_range_assignment_date_lock,
    _remove_range_assignment_in_transaction,
    _validate_and_build_assignment,
    _validity_days,
)


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


def _earliest_weapon_duty_after(
    session: Session, *, soldier_id: uuid.UUID, after_date: date,
) -> date | None:
    """Earliest published weapon-requiring duty starting strictly after ``after_date``.

    Both ``DutyAssignment.is_reserve`` kinds are considered: a range assignment covers
    the soldier's weapon eligibility for regular and reserve duties alike, so either
    kind falling in an uncovered gap is enough to make a later range non-redundant.
    Reuses the exact duty filters of ``_earliest_future_weapon_duty_start``.
    """
    starts = [
        start
        for start in (
            _earliest_future_weapon_duty_start(
                session, soldier_id=soldier_id, is_reserve=is_reserve, after_date=after_date,
            )
            for is_reserve in (False, True)
        )
        if start is not None
    ]
    return min(starts, default=None)


def _refill_slot(
    session: Session, *, event: RangeEvent, is_reserve: bool,
    excluded_soldier_id: uuid.UUID, actor_id: uuid.UUID | None,
) -> RangeAssignment | None:
    """Fill one just-vacated slot on `event` with the best-ranked replacement, without
    committing the transaction. `user=None` keeps the candidate pool at the event's own
    subtree, and the slot kind (`is_reserve`) is preserved exactly — a vacated primary
    is only ever refilled by a primary, and a vacated reserve only by a reserve.
    Returns None when nobody can take the slot; the caller records the shortage."""
    candidates = [
        candidate for candidate in rank_candidates(session, event=event, user=None)
        if candidate.soldier.id != excluded_soldier_id
    ]
    for candidate in candidates:
        try:
            assignment, _constraint = _validate_and_build_assignment(
                session, event=event, soldier_id=candidate.soldier.id,
                is_reserve=is_reserve, user=None,
            )
        except RangeValidationError:
            # The ranked list is already filtered for eligibility, but state can change
            # between ranking and building — skip rather than abort reconciliation.
            continue
        assignment.assignment_reason_code = candidate.reason_code
        session.add(assignment)
        session.flush()
        write_audit(
            session, actor_id=actor_id, action="range_assignment.auto_refill",
            entity_type="range_assignment", entity_id=assignment.id,
            after={
                "soldier_id": str(assignment.soldier_id),
                "range_event_id": str(event.id),
                "is_reserve": is_reserve,
            },
            context={"reason": "redundant_future_range_assignment"},
        )
        return assignment
    return None


def reconcile_future_range_assignments(
    session: Session, *, soldier_id: uuid.UUID, source_event: RangeEvent,
    actor_id: uuid.UUID | None,
) -> ReconciliationResult:
    """Remove redundant later assignments and refill them, without committing.

    The source assignment is the only coverage trigger. Future planned target
    events are visited in date order, and draft assignments are never touched.
    Each vacated slot is immediately offered to the best-ranked replacement from
    the target event's own subtree, keeping the slot kind intact; when nobody can
    take it the slot stays empty and the shortage is counted — the valid removal
    is never rolled back just because no replacement exists.
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

    # A target sits after the source, so the target's OWN coverage window generally
    # reaches further into the future than the source's. Removing it would uncover any
    # weapon duty in that gap — a duty the target covered and the source cannot. One
    # query answers this for every target: the earliest weapon duty past the source's
    # window. Targets are visited in date order, so the per-date advisory locks below
    # are taken in a consistent order with add_range_assignment/assign_batch.
    earliest_uncovered_duty_start = _earliest_weapon_duty_after(
        session, soldier_id=soldier_id, after_date=source_valid_until,
    )

    for assignment, event in targets:
        target_valid_until = event.date + timedelta(
            days=_validity_days(session, event.range_type),
        )
        if (
            earliest_uncovered_duty_start is not None
            and earliest_uncovered_duty_start <= target_valid_until
        ):
            continue

        _acquire_range_assignment_date_lock(session, event_date=event.date)
        removed_id, is_reserve = assignment.id, assignment.is_reserve
        _remove_range_assignment_in_transaction(
            session,
            assignment=assignment,
            reason="redundant_future_range_assignment",
            actor_id=actor_id,
        )
        result.removed_assignment_ids.append(removed_id)

        replacement = _refill_slot(
            session, event=event, is_reserve=is_reserve,
            excluded_soldier_id=soldier_id, actor_id=actor_id,
        )
        if replacement is None:
            if is_reserve:
                result.unfilled_reserve_count += 1
            else:
                result.unfilled_primary_count += 1
        elif is_reserve:
            result.refilled_reserve_assignment_ids.append(replacement.id)
        else:
            result.refilled_primary_assignment_ids.append(replacement.id)

    return result
