from __future__ import annotations

import uuid
from datetime import date
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment,
    DutyType,
    HierarchyNode,
    NotificationType,
    RANGE_TYPE_RANK,
    RangeAssignment,
    RangeEvent,
    RangeEventStatus,
    Soldier,
    SoldierRangeQualification,
)
from app.services.constraints import get_approved_constraint_dates
from app.services.notifications import create_notification
from app.services.range_exemption import is_range_exempt
from app.services.ranges import RangeValidationError


def _qualification_types_at_or_above(range_type: str) -> list[str]:
    min_rank = RANGE_TYPE_RANK[range_type]
    return [rt for rt, rank in RANGE_TYPE_RANK.items() if rank >= min_rank]


def _best_qualification_valid_until(
    session: Session, *, soldier_id: uuid.UUID, range_type: str, as_of: date,
) -> date | None:
    """Among the soldier's still-valid (valid_until >= as_of) qualification rows at
    range_type or higher, returns the valid_until of the most permissive (highest-rank)
    one, or None if the soldier has no such row."""
    candidate_types = _qualification_types_at_or_above(range_type)
    rows = session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier_id,
            SoldierRangeQualification.range_type.in_(candidate_types),
            SoldierRangeQualification.valid_until >= as_of,
        )
    ).scalars().all()
    if not rows:
        return None
    best = max(rows, key=lambda r: RANGE_TYPE_RANK[r.range_type])
    return best.valid_until


def _earliest_future_weapon_duty_start(session: Session, *, soldier_id: uuid.UUID) -> date | None:
    return session.execute(
        select(func.min(DutyAssignment.start_date))
        .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
        .where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.status == "published",
            DutyAssignment.start_date >= date.today(),
            DutyType.requires_weapon.is_(True),
        )
    ).scalar_one_or_none()


def _has_approved_constraint_on_date(session: Session, *, soldier_id: uuid.UUID, event_date: date) -> bool:
    for start, end in get_approved_constraint_dates(session, soldier_id=soldier_id):
        if start <= event_date <= end:
            return True
    return False


def _has_duty_assignment_on_date(session: Session, *, soldier_id: uuid.UUID, event_date: date) -> bool:
    return session.execute(
        select(DutyAssignment.id).where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.start_date <= event_date,
            DutyAssignment.end_date >= event_date,
        ).limit(1)
    ).scalar_one_or_none() is not None


def _has_range_assignment_on_date(session: Session, *, soldier_id: uuid.UUID, event_date: date) -> bool:
    return session.execute(
        select(RangeAssignment.id)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(RangeAssignment.soldier_id == soldier_id, RangeEvent.date == event_date)
        .limit(1)
    ).scalar_one_or_none() is not None


def _sort_key(session: Session, *, soldier: Soldier, event: RangeEvent) -> tuple:
    qualified_until = _best_qualification_valid_until(
        session, soldier_id=soldier.id, range_type=event.range_type, as_of=event.date,
    )
    if qualified_until is not None:
        return (2, qualified_until, str(soldier.id))
    duty_start = _earliest_future_weapon_duty_start(session, soldier_id=soldier.id)
    if duty_start is not None:
        return (0, duty_start, str(soldier.id))
    return (1, str(soldier.id))


def _candidate_pool(session: Session, *, event: RangeEvent, exclude_soldier_ids: set[uuid.UUID]) -> list[Soldier]:
    subtree_node_ids = list(
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.path_ids.any(event.hierarchy_node_id))  # type: ignore[arg-type]
        ).scalars().all()
    )
    soldiers = session.execute(
        select(Soldier).where(Soldier.hierarchy_node_id.in_(subtree_node_ids))
    ).scalars().all()

    pool: list[Soldier] = []
    for soldier in soldiers:
        if soldier.id in exclude_soldier_ids:
            continue
        if is_range_exempt(session, soldier=soldier, event_date=event.date):
            continue
        if _has_approved_constraint_on_date(session, soldier_id=soldier.id, event_date=event.date):
            continue
        if _has_duty_assignment_on_date(session, soldier_id=soldier.id, event_date=event.date):
            continue
        if _has_range_assignment_on_date(session, soldier_id=soldier.id, event_date=event.date):
            continue
        pool.append(soldier)
    return pool


def propose_range_assignments(
    session: Session, *, event: RangeEvent,
) -> tuple[list[RangeAssignment], int]:
    """Fills the event's currently-empty primary/reserve slots with draft
    RangeAssignment rows (is_draft=True), ranked by the Phase 2 tier ordering.
    Returns (created_drafts, shortfall) where shortfall is how many slots
    could not be filled because the candidate pool ran out."""
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")

    existing = session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    existing_soldier_ids = {a.soldier_id for a in existing}
    remaining_primary = max(event.required_count - sum(1 for a in existing if not a.is_reserve), 0)
    remaining_reserve = max(event.reserve_count - sum(1 for a in existing if a.is_reserve), 0)
    total_needed = remaining_primary + remaining_reserve
    if total_needed == 0:
        return [], 0

    pool = _candidate_pool(session, event=event, exclude_soldier_ids=existing_soldier_ids)
    ranked = sorted(pool, key=lambda s: _sort_key(session, soldier=s, event=event))

    chosen = ranked[:total_needed]
    shortfall = total_needed - len(chosen)

    created: list[RangeAssignment] = []
    for index, soldier in enumerate(chosen):
        assignment = RangeAssignment(
            range_event_id=event.id, soldier_id=soldier.id,
            is_reserve=index >= remaining_primary, is_draft=True,
        )
        session.add(assignment)
        created.append(assignment)

    session.commit()
    for assignment in created:
        session.refresh(assignment)
    return created, shortfall


def confirm_draft_assignment(
    session: Session, *, assignment: RangeAssignment, actor_id: uuid.UUID | None = None,
) -> RangeAssignment:
    if not assignment.is_draft:
        raise RangeValidationError("assignment_not_draft")

    assignment.is_draft = False
    write_audit(
        session, actor_id=actor_id, action="range_assignment_confirm", entity_type="range_assignment",
        entity_id=assignment.id, before={"is_draft": True}, after={"is_draft": False},
    )
    create_notification(
        session, soldier_id=assignment.soldier_id, type=NotificationType.range_assignment_confirmed,
        title="שובצת למטווח", reference_type="range_assignment", reference_id=assignment.id, actor_id=actor_id,
    )
    session.commit()
    session.refresh(assignment)
    return assignment


def confirm_all_drafts(
    session: Session, *, event: RangeEvent, actor_id: uuid.UUID | None = None,
) -> list[RangeAssignment]:
    drafts = session.execute(
        select(RangeAssignment).where(
            RangeAssignment.range_event_id == event.id, RangeAssignment.is_draft.is_(True),
        )
    ).scalars().all()
    return [confirm_draft_assignment(session, assignment=d, actor_id=actor_id) for d in drafts]
