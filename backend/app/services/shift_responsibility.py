from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyShift, HierarchyNode
from app.services.node_effort_potential import compute_node_effort_potential


@dataclass
class ShiftResponsibilityAssignment:
    shift_id: uuid.UUID
    hierarchy_node_id: uuid.UUID
    node_name: str


def auto_assign_responsibility(
    session: Session, *, shift_ids: list[uuid.UUID], reference_date: date | None = None
) -> list[ShiftResponsibilityAssignment]:
    """For each shift (processed in start_date order), pick exactly one
    candidate unit = union of direct children of the shift's eligible_node_ids,
    scored by final_potential - (total_effort + running_batch_load), where
    running_batch_load accumulates required_count for whichever unit was
    picked by earlier shifts in this same batch (fair-share within the batch).
    Shifts with no eligible_node_ids, or whose eligible nodes have no direct
    children, are omitted from the result."""
    ref = reference_date or date.today()
    shifts = list(
        session.execute(select(DutyShift).where(DutyShift.id.in_(shift_ids))).scalars().all()
    )
    ordered_shifts = sorted(shifts, key=lambda s: (s.start_date, s.id))

    effort_potential = compute_node_effort_potential(session, reference_date=ref)
    running_batch_load: dict[uuid.UUID, float] = defaultdict(float)

    results: list[ShiftResponsibilityAssignment] = []
    for shift in ordered_shifts:
        if not shift.eligible_node_ids:
            continue
        candidate_ids: set[uuid.UUID] = set()
        for parent_id in shift.eligible_node_ids:
            children = session.execute(
                select(HierarchyNode).where(HierarchyNode.parent_id == parent_id)
            ).scalars().all()
            candidate_ids.update(c.id for c in children)
        if not candidate_ids:
            continue

        def score(node_id: uuid.UUID) -> float:
            ep = effort_potential.get(node_id)
            potential = ep.final_potential if ep else 0
            past_effort = ep.total_effort if ep else 0.0
            return potential - (past_effort + running_batch_load[node_id])

        best_id = max(candidate_ids, key=lambda nid: (score(nid), str(nid)))
        best_node = session.get(HierarchyNode, best_id)
        results.append(
            ShiftResponsibilityAssignment(shift_id=shift.id, hierarchy_node_id=best_id, node_name=best_node.name)
        )
        running_batch_load[best_id] += shift.required_count
    return results
