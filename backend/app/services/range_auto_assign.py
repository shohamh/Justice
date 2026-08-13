from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.algorithm.types import node_in_scope
from app.auth.authz import scope_root_ids
from app.db.models import (
    RANGE_TYPE_RANK,
    DutyAssignment,
    DutyType,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    RangeAssignment,
    RangeEvent,
    Soldier,
    SoldierExemption,
    SoldierRangeQualification,
)


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


def _earliest_future_weapon_duty_start(
    session: Session, *, soldier_id: uuid.UUID, is_reserve: bool,
) -> date | None:
    return session.execute(
        select(func.min(DutyAssignment.start_date))
        .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
        .where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.status == "published",
            DutyAssignment.start_date >= date.today(),
            DutyAssignment.is_reserve == is_reserve,
            DutyType.requires_weapon.is_(True),
        )
    ).scalar_one_or_none()


def _last_qualification_valid_until(
    session: Session, *, soldier_id: uuid.UUID, range_type: str,
) -> date | None:
    """Most recent valid_until among the soldier's qualification rows at range_type or
    higher, whether or not it's still valid — used to explain how long they've been
    unqualified. None if they've never held one."""
    candidate_types = _qualification_types_at_or_above(range_type)
    return session.execute(
        select(func.max(SoldierRangeQualification.valid_until)).where(
            SoldierRangeQualification.soldier_id == soldier_id,
            SoldierRangeQualification.range_type.in_(candidate_types),
        )
    ).scalar_one_or_none()


def _rank_candidate(session: Session, *, soldier: Soldier, event: RangeEvent) -> tuple[tuple, str, str]:
    """Returns (sort_key, reason_code, explanation). Tier order (lowest sorts first,
    i.e. highest priority to be sent to this range): soldiers with an upcoming
    weapon-requiring duty (regular before reserve) need to qualify before that duty;
    soldiers with neither an upcoming duty nor a valid qualification are next; already-
    qualified soldiers sort last, tie-broken by soonest-expiring qualification first."""
    qualified_until = _best_qualification_valid_until(
        session, soldier_id=soldier.id, range_type=event.range_type, as_of=event.date,
    )
    if qualified_until is not None:
        explanation = f"כשירות תקפה עד {qualified_until.strftime('%d.%m.%Y')}"
        return (3, qualified_until, str(soldier.id)), "qualified", explanation

    duty_start = _earliest_future_weapon_duty_start(session, soldier_id=soldier.id, is_reserve=False)
    if duty_start is not None:
        explanation = f"תורנות קרובה ב-{duty_start.strftime('%d.%m.%Y')}"
        return (0, duty_start, str(soldier.id)), "duty_priority", explanation

    reserve_duty_start = _earliest_future_weapon_duty_start(session, soldier_id=soldier.id, is_reserve=True)
    if reserve_duty_start is not None:
        explanation = f"תורנות רזרבה קרובה ב-{reserve_duty_start.strftime('%d.%m.%Y')}"
        return (1, reserve_duty_start, str(soldier.id)), "reserve_duty_priority", explanation

    last_valid_until = _last_qualification_valid_until(
        session, soldier_id=soldier.id, range_type=event.range_type,
    )
    explanation = (
        f"אין מטווחים בתוקף מ-{last_valid_until.strftime('%d.%m.%Y')}"
        if last_valid_until is not None
        else "מעולם לא ביצע מטווחים"
    )
    return (2, str(soldier.id)), "available_and_balanced", explanation


@dataclass
class RankedCandidate:
    soldier: Soldier
    reason_code: str
    explanation: str
    conflict_warning: str | None


NEAR_DUTY_WINDOW_DAYS = 30


def _soldier_pool(session: Session, *, event: RangeEvent, user: Soldier) -> list[Soldier]:
    """Every soldier the requesting user is authorized to send to this range: the
    full union of their commanded/duty-manager subtrees, not just the event's own
    hierarchy node. A commander whose scope spans several sub-units must be able to
    pick reserves from any of them, not only the specific unit the event was created
    under — otherwise the reserve pool dries up as soon as that one unit is full."""
    if user.role == "admin":
        return list(session.execute(select(Soldier)).scalars().all())
    roots = scope_root_ids(session, user)
    if not roots:
        return []
    subtree_node_ids = list(
        session.execute(
            select(HierarchyNode.id).where(
                or_(*(HierarchyNode.path_ids.any(root) for root in roots))  # type: ignore[arg-type]
            )
        ).scalars().all()
    )
    return list(
        session.execute(
            select(Soldier).where(Soldier.hierarchy_node_id.in_(subtree_node_ids))
        ).scalars().all()
    )


def _bulk_duty_start_by_soldier(
    session: Session, *, soldier_ids: list[uuid.UUID],
) -> dict[tuple[uuid.UUID, bool], date]:
    """{(soldier_id, is_reserve): earliest future published weapon-requiring duty
    start}, one bulk query shared by ranking and eligibility."""
    return {
        (soldier_id, is_reserve): start
        for soldier_id, is_reserve, start in session.execute(
            select(DutyAssignment.soldier_id, DutyAssignment.is_reserve, func.min(DutyAssignment.start_date))
            .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
            .where(
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.status == "published",
                DutyAssignment.start_date >= date.today(),
                DutyType.requires_weapon.is_(True),
            )
            .group_by(DutyAssignment.soldier_id, DutyAssignment.is_reserve)
        ).all()
    }


def _bulk_eligibility(
    session: Session, *, soldiers: list[Soldier], event: RangeEvent,
    duty_start_by_soldier: dict[tuple[uuid.UUID, bool], date],
) -> dict[uuid.UUID, str | None]:
    """{soldier_id: conflict_warning} for soldiers who may appear in the candidate
    list at all. Uses the same eligibility rules as range_exemption.is_range_exempt
    and _validate_and_build_assignment's other hard checks, batched across the whole
    candidate set instead of per soldier.

    A soldier is entirely OMITTED from the result (hard-excluded from the candidate
    list) if they have a weapons-forbidding exemption, are structurally ineligible
    for every weapon duty type, or are already assigned to a different range the
    same day — all of these also fail actual assignment, so there's never a reason
    to show them.

    A soldier blocked only by a personal constraint or an overlapping duty
    assignment is a softer, schedule-level conflict that _validate_and_build_
    assignment does NOT reject — so they stay eligible, UNLESS they also have a
    weapon-requiring duty within NEAR_DUTY_WINDOW_DAYS days that needs this
    qualification, in which case they're kept (with a conflict_warning describing
    what needs resolving) so a commander can consciously override rather than have
    them silently disappear from the pool for someone who urgently needs this range."""
    soldier_ids = [s.id for s in soldiers]

    weapon_duty_types = session.execute(
        select(DutyType).where(DutyType.requires_weapon.is_(True), DutyType.active.is_(True))
    ).scalars().all()
    node_ids = {s.hierarchy_node_id for s in soldiers if s.hierarchy_node_id is not None}
    nodes_by_id = {
        n.id: n for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
        ).scalars().all()
    } if node_ids else {}

    exempted: set[uuid.UUID] = set()
    for exemption, exemption_type in session.execute(
        select(SoldierExemption, ExemptionType)
        .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
        .where(
            SoldierExemption.soldier_id.in_(soldier_ids),
            SoldierExemption.revoked_at.is_(None),
            SoldierExemption.start_date <= event.date,
        )
    ).all():
        if exemption.end_date is not None and exemption.end_date < event.date:
            continue
        if exemption_type.is_global or exemption_type.forbids_weapons:
            exempted.add(exemption.soldier_id)

    constraint_by_soldier: dict[uuid.UUID, PersonalConstraint] = {
        c.soldier_id: c for c in session.execute(
            select(PersonalConstraint).where(
                PersonalConstraint.soldier_id.in_(soldier_ids),
                PersonalConstraint.status == "approved",
                PersonalConstraint.start_date <= event.date,
                PersonalConstraint.end_date >= event.date,
            )
        ).scalars().all()
    }

    duty_conflict_by_soldier: dict[uuid.UUID, tuple[DutyAssignment, str]] = {
        duty.soldier_id: (duty, duty_type_name)
        for duty, duty_type_name in session.execute(
            select(DutyAssignment, DutyType.name)
            .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
            .where(
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.start_date <= event.date,
                DutyAssignment.end_date > event.date,
            )
        ).all()
    }

    at_other_range = set(session.execute(
        select(RangeAssignment.soldier_id)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(RangeAssignment.soldier_id.in_(soldier_ids), RangeEvent.date == event.date)
    ).scalars().all())

    near_duty_cutoff = date.today() + timedelta(days=NEAR_DUTY_WINDOW_DAYS)

    result: dict[uuid.UUID, str | None] = {}
    for soldier in soldiers:
        node = nodes_by_id.get(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
        structurally_exempt = node is None or not any(
            node_in_scope(dt.eligible_node_ids, node.path_ids) for dt in weapon_duty_types
        )
        if soldier.id in exempted or structurally_exempt or soldier.id in at_other_range:
            continue

        constraint = constraint_by_soldier.get(soldier.id)
        duty_conflict = duty_conflict_by_soldier.get(soldier.id)
        if constraint is None and duty_conflict is None:
            result[soldier.id] = None
            continue

        has_near_duty = any(
            start is not None and start <= near_duty_cutoff
            for start in (
                duty_start_by_soldier.get((soldier.id, False)),
                duty_start_by_soldier.get((soldier.id, True)),
            )
        )
        if not has_near_duty:
            continue

        parts: list[str] = []
        if constraint is not None:
            parts.append(
                f"אילוץ מאושר {constraint.start_date.strftime('%d.%m.%Y')}"
                f"–{constraint.end_date.strftime('%d.%m.%Y')}"
            )
        if duty_conflict is not None:
            duty, duty_type_name = duty_conflict
            parts.append(f"משובץ לתורנות '{duty_type_name}' ב-{duty.start_date.strftime('%d.%m.%Y')}")
        result[soldier.id] = " · ".join(parts)
    return result


def _bulk_rank(
    session: Session, *, soldiers: list[Soldier], event: RangeEvent,
    duty_start_by_soldier: dict[tuple[uuid.UUID, bool], date],
) -> dict[uuid.UUID, tuple[tuple, str, str]]:
    """Bulk equivalent of _rank_candidate: same tier logic, but the qualification
    lookup it depends on is fetched once for the whole candidate set."""
    soldier_ids = [s.id for s in soldiers]
    candidate_types = _qualification_types_at_or_above(event.range_type)

    quals_by_soldier: dict[uuid.UUID, list[SoldierRangeQualification]] = defaultdict(list)
    for q in session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id.in_(soldier_ids),
            SoldierRangeQualification.range_type.in_(candidate_types),
        )
    ).scalars().all():
        quals_by_soldier[q.soldier_id].append(q)

    result: dict[uuid.UUID, tuple[tuple, str, str]] = {}
    for soldier in soldiers:
        rows = quals_by_soldier.get(soldier.id, [])
        valid_rows = [r for r in rows if r.valid_until >= event.date]
        if valid_rows:
            best = max(valid_rows, key=lambda r: RANGE_TYPE_RANK[r.range_type])
            explanation = f"כשירות תקפה עד {best.valid_until.strftime('%d.%m.%Y')}"
            result[soldier.id] = ((3, best.valid_until, str(soldier.id)), "qualified", explanation)
            continue

        duty_start = duty_start_by_soldier.get((soldier.id, False))
        if duty_start is not None:
            explanation = f"תורנות קרובה ב-{duty_start.strftime('%d.%m.%Y')}"
            result[soldier.id] = ((0, duty_start, str(soldier.id)), "duty_priority", explanation)
            continue

        reserve_duty_start = duty_start_by_soldier.get((soldier.id, True))
        if reserve_duty_start is not None:
            explanation = f"תורנות רזרבה קרובה ב-{reserve_duty_start.strftime('%d.%m.%Y')}"
            result[soldier.id] = ((1, reserve_duty_start, str(soldier.id)), "reserve_duty_priority", explanation)
            continue

        last_valid_until = max((r.valid_until for r in rows), default=None)
        explanation = (
            f"אין מטווחים בתוקף מ-{last_valid_until.strftime('%d.%m.%Y')}"
            if last_valid_until is not None
            else "מעולם לא ביצע מטווחים"
        )
        result[soldier.id] = ((2, str(soldier.id)), "available_and_balanced", explanation)
    return result


def rank_candidates(session: Session, *, event: RangeEvent, user: Soldier) -> list[RankedCandidate]:
    """Read-only: ranks every ELIGIBLE soldier in the requesting user's authorized
    scope who isn't already assigned to this event, using the Phase 2 tier ordering,
    but never writes to the database. Soldiers who can't actually be sent to this
    range (exemption, structural ineligibility, already assigned elsewhere the same
    day) never appear here at all — see _bulk_eligibility for the one deliberate
    exception (an urgent upcoming duty overriding a scheduling-only conflict)."""
    existing_soldier_ids = {
        a.soldier_id for a in session.execute(
            select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
        ).scalars().all()
    }
    soldiers = [s for s in _soldier_pool(session, event=event, user=user) if s.id not in existing_soldier_ids]
    if not soldiers:
        return []

    duty_start_by_soldier = _bulk_duty_start_by_soldier(session, soldier_ids=[s.id for s in soldiers])
    eligibility = _bulk_eligibility(
        session, soldiers=soldiers, event=event, duty_start_by_soldier=duty_start_by_soldier,
    )
    eligible_soldiers = [s for s in soldiers if s.id in eligibility]
    if not eligible_soldiers:
        return []

    ranks = _bulk_rank(session, soldiers=eligible_soldiers, event=event, duty_start_by_soldier=duty_start_by_soldier)

    ranked = [
        RankedCandidate(
            soldier=soldier, reason_code=ranks[soldier.id][1], explanation=ranks[soldier.id][2],
            conflict_warning=eligibility[soldier.id],
        )
        for soldier in eligible_soldiers
    ]
    ranked.sort(key=lambda c: ranks[c.soldier.id][0])
    return ranked
