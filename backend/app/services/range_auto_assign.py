from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

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
from app.services.constraint_override_settings import manual_override_allowed
from app.services.range_coverage import RangeCoverage, get_range_coverage, get_range_coverages, relevant_duty_types
from app.services.ranges import _validity_days


def _qualification_types_at_or_above(range_type: str) -> list[str]:
    min_rank = RANGE_TYPE_RANK[range_type]
    return [rt for rt, rank in RANGE_TYPE_RANK.items() if rank >= min_rank]


def _earliest_future_weapon_duty_start(
    session: Session, *, soldier_id: uuid.UUID, is_reserve: bool, after_date: date,
) -> date | None:
    return session.execute(
        select(func.min(DutyAssignment.start_date))
        .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
        .where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.status == "published",
            DutyAssignment.start_date > after_date,
            DutyAssignment.is_reserve == is_reserve,
            DutyType.requires_weapon.is_(True),
        )
    ).scalar_one_or_none()


def _earliest_future_range_relevant_duty_start(
    session: Session, *, soldier_id: uuid.UUID, is_reserve: bool, after_date: date,
    relevant_duty_type_ids: list[uuid.UUID],
) -> date | None:
    """Like `_earliest_future_weapon_duty_start`, but scoped to `relevant_duty_type_ids`
    (see `relevant_duty_types`) — used for candidate ranking, where a soldier's
    urgent laser-tier duty must not boost their priority for an alal event they
    don't structurally need. Takes the id list rather than a range_type so callers
    checking both `is_reserve` kinds for the same event compute it once."""
    if not relevant_duty_type_ids:
        return None
    return session.execute(
        select(func.min(DutyAssignment.start_date)).where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.status == "published",
            DutyAssignment.start_date > after_date,
            DutyAssignment.is_reserve == is_reserve,
            DutyAssignment.duty_type_id.in_(relevant_duty_type_ids),
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


def _rank_from_coverage(
    *, soldier_id: uuid.UUID, coverage: RangeCoverage, duty_start: date | None,
    reserve_duty_start: date | None, last_valid_until: date | None,
    event_date: date, validity_days: int,
) -> tuple[tuple, str, str, bool]:
    """Return a candidate rank from already-bulk-loaded coverage and duty facts."""
    if coverage.coverage_kind in {"qualification", "primary_range"}:
        assert coverage.valid_until is not None
        explanation_prefix = (
            "כשירות תקפה עד"
            if coverage.coverage_kind == "qualification"
            else "מטווח ראשי תקף עד"
        )
        explanation = f"{explanation_prefix} {coverage.valid_until.strftime('%d.%m.%Y')}"
        recently_qualified = (
            coverage.source_event_date is not None
            and (event_date - coverage.source_event_date).days * 2 < validity_days
        )
        if recently_qualified:
            return (4, coverage.valid_until, str(soldier_id)), "qualified", explanation, False
        return (3, coverage.valid_until, str(soldier_id)), "qualified", explanation, True

    if duty_start is not None:
        explanation = f"תורנות קרובה ב-{duty_start.strftime('%d.%m.%Y')}"
        return (0, duty_start, str(soldier_id)), "duty_priority", explanation, True

    if reserve_duty_start is not None:
        explanation = f"תורנות רזרבה קרובה ב-{reserve_duty_start.strftime('%d.%m.%Y')}"
        return (1, reserve_duty_start, str(soldier_id)), "reserve_duty_priority", explanation, True

    explanation = (
        f"אין מטווחים בתוקף מ-{last_valid_until.strftime('%d.%m.%Y')}"
        if last_valid_until is not None
        else "מעולם לא ביצע מטווחים"
    )
    return (2, str(soldier_id)), "available_and_balanced", explanation, True


def _rank_candidate(session: Session, *, soldier: Soldier, event: RangeEvent) -> tuple[tuple, str, str, bool]:
    """Single-soldier counterpart of the bounded candidate-list ranking path."""
    coverage = get_range_coverage(
        session, soldier_id=soldier.id, required_range_type=event.range_type, as_of=event.date,
    )
    relevant_duty_type_ids = [dt.id for dt in relevant_duty_types(session, range_type=event.range_type)]
    return _rank_from_coverage(
        soldier_id=soldier.id,
        coverage=coverage,
        duty_start=_earliest_future_range_relevant_duty_start(
            session, soldier_id=soldier.id, is_reserve=False, after_date=event.date,
            relevant_duty_type_ids=relevant_duty_type_ids,
        ),
        reserve_duty_start=_earliest_future_range_relevant_duty_start(
            session, soldier_id=soldier.id, is_reserve=True, after_date=event.date,
            relevant_duty_type_ids=relevant_duty_type_ids,
        ),
        last_valid_until=_last_qualification_valid_until(
            session, soldier_id=soldier.id, range_type=event.range_type,
        ),
        event_date=event.date,
        validity_days=_validity_days(session, coverage.source_range_type or event.range_type),
    )


@dataclass
class RankedCandidate:
    soldier: Soldier
    reason_code: str
    explanation: str
    conflict_warning: str | None
    personal_constraint_conflict: bool = False
    auto_selectable: bool = True


@dataclass(frozen=True)
class ExcludedSoldier:
    soldier_id: uuid.UUID
    reason: Literal["weapon_exempt", "structurally_ineligible", "assigned_elsewhere_same_day", "personal_constraint"]


NEAR_DUTY_WINDOW_DAYS = 30


def _soldiers_under_roots(session: Session, *, roots: list[uuid.UUID]) -> list[Soldier]:
    """Every soldier whose hierarchy node lies in the subtree of any of `roots`."""
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


def _soldier_pool(session: Session, *, event: RangeEvent, user: Soldier | None = None) -> list[Soldier]:
    """Every soldier the requesting user is authorized to send to this range: the
    full union of their commanded/duty-manager subtrees, not just the event's own
    hierarchy node. A commander whose scope spans several sub-units must be able to
    pick reserves from any of them, not only the specific unit the event was created
    under — otherwise the reserve pool dries up as soon as that one unit is full.

    user=None (no caller context, e.g. reconciliation's automatic refill) means there
    is no widened authorized scope to apply, so the pool is exactly the event's own
    subtree — the same rule _validate_and_build_assignment applies via in_event_subtree."""
    if user is None:
        return _soldiers_under_roots(session, roots=[event.hierarchy_node_id])
    if user.role == "admin":
        return list(session.execute(select(Soldier)).scalars().all())
    roots = scope_root_ids(session, user)
    if not roots:
        return []
    return _soldiers_under_roots(session, roots=roots)


def _bulk_duty_start_by_soldier(
    session: Session, *, soldier_ids: list[uuid.UUID], start_date: date, include_start_date: bool,
) -> dict[tuple[uuid.UUID, bool], date]:
    """Return earliest published weapon duties by soldier and assignment kind."""
    start_date_filter = (
        DutyAssignment.start_date >= start_date
        if include_start_date
        else DutyAssignment.start_date > start_date
    )
    return {
        (soldier_id, is_reserve): start
        for soldier_id, is_reserve, start in session.execute(
            select(DutyAssignment.soldier_id, DutyAssignment.is_reserve, func.min(DutyAssignment.start_date))
            .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
            .where(
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.status == "published",
                start_date_filter,
                DutyType.requires_weapon.is_(True),
            )
            .group_by(DutyAssignment.soldier_id, DutyAssignment.is_reserve)
        ).all()
    }


def _bulk_range_relevant_duty_start_by_soldier(
    session: Session, *, soldier_ids: list[uuid.UUID], start_date: date, include_start_date: bool,
    range_type: str,
) -> dict[tuple[uuid.UUID, bool], date]:
    """Bulk counterpart of `_earliest_future_range_relevant_duty_start`: earliest
    published duty by soldier and assignment kind, scoped to duty types this
    `range_type` is actually relevant to — used for candidate ranking priority."""
    duty_type_ids = [dt.id for dt in relevant_duty_types(session, range_type=range_type)]
    if not duty_type_ids or not soldier_ids:
        return {}
    start_date_filter = (
        DutyAssignment.start_date >= start_date
        if include_start_date
        else DutyAssignment.start_date > start_date
    )
    return {
        (soldier_id, is_reserve): start
        for soldier_id, is_reserve, start in session.execute(
            select(DutyAssignment.soldier_id, DutyAssignment.is_reserve, func.min(DutyAssignment.start_date))
            .where(
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.status == "published",
                start_date_filter,
                DutyAssignment.duty_type_id.in_(duty_type_ids),
            )
            .group_by(DutyAssignment.soldier_id, DutyAssignment.is_reserve)
        ).all()
    }


def _bulk_eligibility(
    session: Session, *, soldiers: list[Soldier], event: RangeEvent,
    duty_start_by_soldier: dict[tuple[uuid.UUID, bool], date],
) -> tuple[dict[uuid.UUID, str | None], list[ExcludedSoldier], set[uuid.UUID]]:
    """({soldier_id: conflict_warning}, excluded) for soldiers who may appear in
    the candidate list at all. Uses the same eligibility rules as
    range_exemption.is_range_exempt and _validate_and_build_assignment's other
    hard checks, batched across the whole candidate set instead of per soldier.

    A soldier is entirely OMITTED from the result dict (hard-excluded from the
    candidate list, but recorded in `excluded` with a reason) if they have a
    weapons-forbidding exemption, are structurally ineligible for every duty type
    this event's range_type is relevant to (see `relevant_duty_types` — a soldier
    who only ever needs laser is ineligible for an alal event), or are already
    assigned to a different range the same day — all of these also fail actual
    assignment, so there's never a reason to show them as a candidate.

    A soldier with an approved personal constraint overlapping the event date is
    handled according to the constraints.allow_manual_override system setting: if
    overriding is allowed, they stay eligible with an unconditional conflict_warning
    (no near-duty condition — a commander can consciously override); if overriding
    is disallowed, they're hard-excluded with reason "personal_constraint".

    A soldier blocked only by an overlapping duty assignment (no personal
    constraint) is a softer, schedule-level conflict that _validate_and_build_
    assignment does NOT reject — so they stay eligible, UNLESS they also have a
    weapon-requiring duty within NEAR_DUTY_WINDOW_DAYS days that needs this
    qualification, in which case they're kept (with a conflict_warning describing
    what needs resolving) so a commander can consciously override rather than have
    them silently disappear from the pool for someone who urgently needs this range."""
    soldier_ids = [s.id for s in soldiers]
    override_allowed = manual_override_allowed(session)

    range_relevant_types = relevant_duty_types(session, range_type=event.range_type)
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

    excluded: list[ExcludedSoldier] = []
    result: dict[uuid.UUID, str | None] = {}
    constraint_conflict_ids: set[uuid.UUID] = set()
    for soldier in soldiers:
        node = nodes_by_id.get(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
        structurally_exempt = node is None or not any(
            node_in_scope(dt.eligible_node_ids, node.path_ids) for dt in range_relevant_types
        )
        if soldier.id in exempted:
            excluded.append(ExcludedSoldier(soldier.id, "weapon_exempt"))
            continue
        if structurally_exempt:
            excluded.append(ExcludedSoldier(soldier.id, "structurally_ineligible"))
            continue
        if soldier.id in at_other_range:
            excluded.append(ExcludedSoldier(soldier.id, "assigned_elsewhere_same_day"))
            continue

        constraint = constraint_by_soldier.get(soldier.id)
        duty_conflict = duty_conflict_by_soldier.get(soldier.id)

        if constraint is not None and not override_allowed:
            excluded.append(ExcludedSoldier(soldier.id, "personal_constraint"))
            continue

        if constraint is None and duty_conflict is None:
            result[soldier.id] = None
            continue

        if constraint is not None:
            # Setting ON: always warn (dropping the previous near-duty gate).
            parts: list[str] = [
                f"אילוץ מאושר {constraint.start_date.strftime('%d.%m.%Y')}"
                f"–{constraint.end_date.strftime('%d.%m.%Y')}"
            ]
            if duty_conflict is not None:
                duty, duty_type_name = duty_conflict
                parts.append(f"משובץ לתורנות '{duty_type_name}' ב-{duty.start_date.strftime('%d.%m.%Y')}")
            result[soldier.id] = " · ".join(parts)
            constraint_conflict_ids.add(soldier.id)
            continue

        # No constraint — keep the existing near-duty-gated duty_conflict warning.
        has_near_duty = any(
            start is not None and start <= near_duty_cutoff
            for start in (
                duty_start_by_soldier.get((soldier.id, False)),
                duty_start_by_soldier.get((soldier.id, True)),
            )
        )
        if not has_near_duty:
            continue
        duty, duty_type_name = duty_conflict
        result[soldier.id] = f"משובץ לתורנות '{duty_type_name}' ב-{duty.start_date.strftime('%d.%m.%Y')}"
    return result, excluded, constraint_conflict_ids


def _bulk_rank(
    session: Session, *, soldiers: list[Soldier], event: RangeEvent,
    duty_start_by_soldier: dict[tuple[uuid.UUID, bool], date],
) -> dict[uuid.UUID, tuple[tuple, str, str, bool]]:
    """Bulk candidate ranking using the shared date-aware coverage classification."""
    soldier_ids = [s.id for s in soldiers]
    candidate_types = _qualification_types_at_or_above(event.range_type)

    last_valid_until_by_soldier: dict[uuid.UUID, date] = {}
    for soldier_id, valid_until in session.execute(
        select(SoldierRangeQualification.soldier_id, func.max(SoldierRangeQualification.valid_until))
        .where(
            SoldierRangeQualification.soldier_id.in_(soldier_ids),
            SoldierRangeQualification.range_type.in_(candidate_types),
        )
        .group_by(SoldierRangeQualification.soldier_id)
    ).all():
        last_valid_until_by_soldier[soldier_id] = valid_until

    coverage_by_soldier = get_range_coverages(
        session,
        soldier_ids=soldier_ids,
        required_range_type=event.range_type,
        as_of=event.date,
    )

    return {
        soldier.id: _rank_from_coverage(
            soldier_id=soldier.id,
            coverage=coverage_by_soldier[soldier.id],
            duty_start=duty_start_by_soldier.get((soldier.id, False)),
            reserve_duty_start=duty_start_by_soldier.get((soldier.id, True)),
            last_valid_until=last_valid_until_by_soldier.get(soldier.id),
            event_date=event.date,
            validity_days=_validity_days(
                session, coverage_by_soldier[soldier.id].source_range_type or event.range_type,
            ),
        )
        for soldier in soldiers
    }


def rank_candidates_with_excluded(
    session: Session, *, event: RangeEvent, user: Soldier | None = None,
) -> tuple[list[RankedCandidate], list[ExcludedSoldier]]:
    """Return ranked candidates and hard-excluded soldiers in one read-only pass."""
    existing_soldier_ids = {
        a.soldier_id for a in session.execute(
            select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
        ).scalars().all()
    }
    soldiers = [s for s in _soldier_pool(session, event=event, user=user) if s.id not in existing_soldier_ids]
    if not soldiers:
        return [], []

    soldier_ids = [s.id for s in soldiers]
    warning_duty_start_by_soldier = _bulk_duty_start_by_soldier(
        session, soldier_ids=soldier_ids, start_date=date.today(), include_start_date=True,
    )
    eligibility, excluded, constraint_conflict_ids = _bulk_eligibility(
        session, soldiers=soldiers, event=event, duty_start_by_soldier=warning_duty_start_by_soldier,
    )
    eligible_soldiers = [s for s in soldiers if s.id in eligibility]
    if not eligible_soldiers:
        return [], excluded

    ranking_duty_start_by_soldier = _bulk_range_relevant_duty_start_by_soldier(
        session,
        soldier_ids=[s.id for s in eligible_soldiers],
        start_date=event.date,
        include_start_date=False,
        range_type=event.range_type,
    )
    ranks = _bulk_rank(
        session, soldiers=eligible_soldiers, event=event, duty_start_by_soldier=ranking_duty_start_by_soldier,
    )

    ranked = [
        RankedCandidate(
            soldier=soldier, reason_code=ranks[soldier.id][1], explanation=ranks[soldier.id][2],
            conflict_warning=eligibility[soldier.id],
            personal_constraint_conflict=soldier.id in constraint_conflict_ids,
            auto_selectable=ranks[soldier.id][3],
        )
        for soldier in eligible_soldiers
    ]
    ranked.sort(key=lambda c: ranks[c.soldier.id][0])
    return ranked, excluded


def rank_candidates(
    session: Session, *, event: RangeEvent, user: Soldier | None = None,
) -> list[RankedCandidate]:
    """Read-only: ranks every ELIGIBLE soldier in the requesting user's authorized
    scope who isn't already assigned to this event, using the Phase 2 tier ordering,
    but never writes to the database. Soldiers who can't actually be sent to this
    range (exemption, structural ineligibility, already assigned elsewhere the same
    day) never appear here at all — see _bulk_eligibility for the one deliberate
    exception (an urgent upcoming duty overriding a scheduling-only conflict), and
    see `excluded_candidates` to retrieve those hard-excluded soldiers instead."""
    ranked, _excluded = rank_candidates_with_excluded(session, event=event, user=user)
    return ranked


def excluded_candidates(
    session: Session, *, event: RangeEvent, user: Soldier | None = None,
) -> list[ExcludedSoldier]:
    """Read-only: the soldiers hard-excluded from `rank_candidates`'s pool for this
    event (weapon-exempt, structurally ineligible, or already assigned to another
    range the same day), each with a reason code — so the UI can show *why* a
    soldier the commander expected to see doesn't appear as a candidate."""
    _ranked, excluded = rank_candidates_with_excluded(session, event=event, user=user)
    return excluded
