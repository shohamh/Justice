from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    RANGE_TYPE_RANK,
    DutyAssignment,
    DutyType,
    HierarchyNode,
    RangeAssignment,
    RangeEvent,
    Soldier,
    SoldierRangeQualification,
)
from app.services.constraints import get_approved_constraint_dates
from app.services.range_exemption import is_range_exempt


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
            DutyAssignment.end_date > event_date,
        ).limit(1)
    ).scalar_one_or_none() is not None


def _has_range_assignment_on_date(session: Session, *, soldier_id: uuid.UUID, event_date: date) -> bool:
    return session.execute(
        select(RangeAssignment.id)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(RangeAssignment.soldier_id == soldier_id, RangeEvent.date == event_date)
        .limit(1)
    ).scalar_one_or_none() is not None


def _rank_candidate(session: Session, *, soldier: Soldier, event: RangeEvent) -> tuple[tuple, str]:
    qualified_until = _best_qualification_valid_until(
        session, soldier_id=soldier.id, range_type=event.range_type, as_of=event.date,
    )
    if qualified_until is not None:
        return (2, qualified_until, str(soldier.id)), "qualified"
    duty_start = _earliest_future_weapon_duty_start(session, soldier_id=soldier.id)
    if duty_start is not None:
        return (0, duty_start, str(soldier.id)), "weapon_duty_priority"
    return (1, str(soldier.id)), "available_and_balanced"


@dataclass
class RankedCandidate:
    soldier: Soldier
    reason_code: str
    blocked: bool
    blocked_reason: str | None


def rank_candidates(session: Session, *, event: RangeEvent) -> list[RankedCandidate]:
    """Read-only: ranks every soldier in the event's subtree who isn't already
    assigned to it, using the Phase 2 tier ordering, but never writes to the
    database. Ineligible soldiers (exempt/constrained/already duty- or
    range-assigned that day) are marked blocked=True instead of being
    excluded, so the frontend can show them (greyed out) rather than
    silently omitting them."""
    existing_soldier_ids = {
        a.soldier_id for a in session.execute(
            select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
        ).scalars().all()
    }
    subtree_node_ids = list(
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.path_ids.any(event.hierarchy_node_id))  # type: ignore[arg-type]
        ).scalars().all()
    )
    soldiers = session.execute(
        select(Soldier).where(Soldier.hierarchy_node_id.in_(subtree_node_ids))
    ).scalars().all()

    ranked: list[RankedCandidate] = []
    for soldier in soldiers:
        if soldier.id in existing_soldier_ids:
            continue
        blocked_reason = None
        if is_range_exempt(session, soldier=soldier, event_date=event.date):
            blocked_reason = "exempt"
        elif _has_approved_constraint_on_date(session, soldier_id=soldier.id, event_date=event.date):
            blocked_reason = "constraint"
        elif _has_duty_assignment_on_date(session, soldier_id=soldier.id, event_date=event.date):
            blocked_reason = "duty_assignment"
        elif _has_range_assignment_on_date(session, soldier_id=soldier.id, event_date=event.date):
            blocked_reason = "range_assignment"
        _, reason_code = _rank_candidate(session, soldier=soldier, event=event)
        ranked.append(RankedCandidate(
            soldier=soldier, reason_code=reason_code,
            blocked=blocked_reason is not None, blocked_reason=blocked_reason,
        ))

    def sort_key(c: RankedCandidate) -> tuple:
        rank, _ = _rank_candidate(session, soldier=c.soldier, event=event)
        return (c.blocked, rank)

    ranked.sort(key=sort_key)
    return ranked
