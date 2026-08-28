from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, HierarchyNode, Soldier
from app.services import hierarchy as hierarchy_svc
from app.services.eligibility import check_soldier_for_assignment
from app.services.swaps import SwapError, _enforce_hierarchy_level_restriction


def list_eligible_targets(
    session: Session, *, requesting_soldier_id: uuid.UUID, duty_assignment_id: uuid.UUID
) -> list[dict]:
    """List soldiers who are eligible and available to cover `duty_assignment_id`,
    sorted ascending by hierarchical distance from the requester.

    Excludes the requester themself, soldiers who fail
    `check_soldier_for_assignment`, and soldiers who fall outside any configured
    `swaps.restrict_to_hierarchy_level` restriction (checked per-candidate; a
    SwapError there is swallowed since this is a read-only listing, not a
    mutation)."""
    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        return []
    requester = session.get(Soldier, requesting_soldier_id)
    if requester is None:
        return []

    candidates = session.execute(
        select(Soldier).where(Soldier.id != requesting_soldier_id, Soldier.left_at.is_(None))
    ).scalars().all()

    out: list[dict] = []
    for c in candidates:
        eligible, _reason, _warning = check_soldier_for_assignment(session, c.id, duty_assignment_id)
        if not eligible:
            continue
        try:
            _enforce_hierarchy_level_restriction(
                session, requesting_soldier_id=requesting_soldier_id, other_soldier_id=c.id
            )
        except SwapError:
            continue
        distance = hierarchy_svc.node_distance(
            session, requester.hierarchy_node_id, c.hierarchy_node_id
        )
        node_name = None
        if c.hierarchy_node_id:
            node = session.get(HierarchyNode, c.hierarchy_node_id)
            node_name = node.name if node else None
        out.append({
            "soldier_id": c.id,
            "full_name": c.full_name,
            "node_name": node_name,
            "hierarchy_distance": distance,
        })
    out.sort(key=lambda r: r["hierarchy_distance"])
    return out
