from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyType, ForcedCallup, HierarchyNode, Soldier
from app.algorithm.solver import solve
from app.algorithm.types import DutyBlock, ExistingAssignment, SolverSettings
from app.services.algorithm_bridge import load_soldier_inputs


def _node_ancestors(node_id: uuid.UUID, session: Session) -> list[uuid.UUID]:
    """Return [node_id, parent_id, grandparent_id, ...] walking up the tree."""
    result = []
    nid: uuid.UUID | None = node_id
    while nid:
        node = session.get(HierarchyNode, nid)
        if node is None:
            break
        result.append(node.id)
        nid = node.parent_id
    return result


def _subtree_node_ids(node_id: uuid.UUID, session: Session) -> set[uuid.UUID]:
    """Return node_id and all descendants."""
    result: set[uuid.UUID] = set()
    stack = [node_id]
    while stack:
        nid = stack.pop()
        result.add(nid)
        children = session.execute(
            select(HierarchyNode.id).where(HierarchyNode.parent_id == nid)
        ).scalars().all()
        stack.extend(children)
    return result


def candidate_scope_nodes(pulled_soldier: Soldier, session: Session) -> set[uuid.UUID]:
    """
    Return the set of node IDs eligible to contribute replacement candidates.
    Parent node (one up) and all its descendants.
    """
    if pulled_soldier.hierarchy_node_id is None:
        return {n for n in session.execute(select(HierarchyNode.id)).scalars().all()}
    ancestors = _node_ancestors(pulled_soldier.hierarchy_node_id, session)
    parent_id = ancestors[1] if len(ancestors) > 1 else ancestors[0]
    return _subtree_node_ids(parent_id, session)


def hierarchy_distance(soldier: Soldier, pulled_soldier: Soldier, session: Session) -> int:
    if soldier.hierarchy_node_id is None or pulled_soldier.hierarchy_node_id is None:
        return 99
    if soldier.hierarchy_node_id == pulled_soldier.hierarchy_node_id:
        return 0
    pulled_ancestors = _node_ancestors(pulled_soldier.hierarchy_node_id, session)
    soldier_ancestors = _node_ancestors(soldier.hierarchy_node_id, session)
    pulled_set = {nid: i for i, nid in enumerate(pulled_ancestors)}
    for j, nid in enumerate(soldier_ancestors):
        if nid in pulled_set:
            return pulled_set[nid] + j
    return 99


def recency_decayed_callups(soldier_id: uuid.UUID, session: Session) -> float:
    """Sum of 0.5^(days_since/30) for each הקפצה in last 90 days."""
    cutoff = date.today() - timedelta(days=90)
    callups = session.execute(
        select(ForcedCallup.created_at).where(
            ForcedCallup.replacement_soldier_id == soldier_id,
            ForcedCallup.status == "approved",
            ForcedCallup.created_at >= cutoff,  # type: ignore[arg-type]
        )
    ).scalars().all()
    total = 0.0
    today = date.today()
    for ca in callups:
        days_since = (today - ca.date()).days
        total += 0.5 ** (days_since / 30)
    return round(total, 2)


def find_candidates(
    session: Session,
    *,
    original_assignment_id: uuid.UUID,
    pull_date: date,
    n: int = 8,
) -> list[dict]:
    """Run a solver pass for the remaining slot and return top N candidates."""
    original = session.get(DutyAssignment, original_assignment_id)
    if original is None:
        raise ValueError("assignment not found")

    pulled_soldier = session.get(Soldier, original.soldier_id)
    if pulled_soldier is None:
        raise ValueError("pulled soldier not found")
    scope_node_ids = candidate_scope_nodes(pulled_soldier, session)

    all_inputs = load_soldier_inputs(session, as_of=pull_date)
    candidate_inputs = [
        si for si in all_inputs
        if si.id != original.soldier_id
        and si.hierarchy_node_id in scope_node_ids
    ]

    existing = [
        ExistingAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
        )
        for a in session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.id != original_assignment_id,
            )
        ).scalars().all()
    ]

    dt = session.get(DutyType, original.duty_type_id)
    score_per_day = dt.score_per_day if dt else Decimal("1.0")

    remaining_block = DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=original.duty_type_id,
        duty_location_id=original.duty_location_id,
        start_date=pull_date,
        end_date=original.end_date,
        score_per_day=score_per_day,
        is_reserve=False,
    )

    settings = SolverSettings(T=7, Wt=14, Wr=28, alpha=Decimal("2.0"), time_limit_seconds=10)
    result = solve(candidate_inputs, [remaining_block], existing, settings)

    assigned_ids = {a.soldier_id for a in result.assignments}
    days_remaining = (original.end_date - pull_date).days

    candidates = []
    for si in candidate_inputs:
        if si.id not in assigned_ids:
            continue
        soldier = session.get(Soldier, si.id)
        node = session.get(HierarchyNode, si.hierarchy_node_id) if si.hierarchy_node_id else None
        dist = hierarchy_distance(soldier, pulled_soldier, session) if soldier else 99
        decay = recency_decayed_callups(si.id, session)

        candidates.append({
            "soldier_id": str(si.id),
            "full_name": soldier.full_name if soldier else "—",
            "hierarchy_node_name": node.name if node else "—",
            "hierarchy_distance": dist,
            "current_score": float(si.cumulative_score),
            "score_per_day": float(score_per_day),
            "days_remaining": days_remaining,
            "recent_forced_callups_decayed": decay,
        })

    candidates.sort(key=lambda c: (c["hierarchy_distance"], c["current_score"], c["recent_forced_callups_decayed"]))
    return candidates[:n]
