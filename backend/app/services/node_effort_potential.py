from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode, Soldier
from app.services.potential import compute_potential
from app.services.scoring import effort_scores_by_soldier


@dataclass
class NodeEffortPotential:
    node_id: uuid.UUID
    node_name: str
    final_potential: int
    total_effort: float
    sibling_potential_share: float | None = None
    sibling_effort_share: float | None = None
    sibling_gap: float | None = None
    global_potential_share: float | None = None
    global_effort_share: float | None = None
    global_gap: float | None = None


def compute_node_effort_potential(
    session: Session, *, reference_date: date
) -> dict[uuid.UUID, NodeEffortPotential]:
    """Per-node final_potential, total_effort (sum of per-soldier effort_score
    across the node's subtree), and share/gap ratios both among direct
    siblings and relative to the whole organization (top-level roots)."""
    nodes = list(session.execute(select(HierarchyNode)).scalars().all())
    soldiers = list(
        session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    )
    effort_by_soldier = effort_scores_by_soldier(session, soldiers)

    # node_id -> set of node ids in its own subtree (nodes whose path_ids contains node_id)
    subtree_node_ids_by_node: dict[uuid.UUID, set[uuid.UUID]] = {
        node.id: {n2.id for n2 in nodes if node.id in n2.path_ids} for node in nodes
    }

    # NOTE: O(N) DB round-trips — compute_potential is called once per hierarchy
    # node, and several of its internal queries (active duty types, exemption-type
    # maps) re-fetch identical global data every iteration. Acceptable at current
    # org sizes; revisit (e.g. hoist duty-type/exemption-type lookups out of
    # compute_potential's per-call scope) if hierarchy size grows into the hundreds.
    results: dict[uuid.UUID, NodeEffortPotential] = {}
    for node in nodes:
        potential = compute_potential(
            session, node_id=node.id, reference_date=reference_date
        ).final_potential
        subtree_ids = subtree_node_ids_by_node[node.id]
        total_effort = sum(
            effort_by_soldier.get(s.id, 0.0) for s in soldiers if s.hierarchy_node_id in subtree_ids
        )
        results[node.id] = NodeEffortPotential(
            node_id=node.id,
            node_name=node.name,
            final_potential=potential,
            total_effort=total_effort,
        )

    def _apply_shares(group: list[HierarchyNode], potential_attr: str, effort_attr: str, gap_attr: str) -> None:
        total_potential = sum(max(results[n.id].final_potential, 0) for n in group)
        total_effort = sum(results[n.id].total_effort for n in group)
        for n in group:
            r = results[n.id]
            p_share = (max(r.final_potential, 0) / total_potential) if total_potential > 0 else None
            e_share = (r.total_effort / total_effort) if total_effort > 0 else None
            setattr(r, potential_attr, p_share)
            setattr(r, effort_attr, e_share)
            # Gap is intentionally left None (not infinity) when potential share is
            # zero, even if effort share is nonzero (e.g. negative final_potential
            # clamped to 0) — callers must distinguish "no data" from "zero potential".
            if p_share is not None and p_share > 0 and e_share is not None:
                setattr(r, gap_attr, e_share / p_share)

    by_parent: dict[uuid.UUID | None, list[HierarchyNode]] = defaultdict(list)
    for node in nodes:
        by_parent[node.parent_id].append(node)
    for siblings in by_parent.values():
        _apply_shares(siblings, "sibling_potential_share", "sibling_effort_share", "sibling_gap")

    top_level_roots = [n for n in nodes if n.parent_id is None]
    if top_level_roots:
        _apply_shares(top_level_roots, "global_potential_share", "global_effort_share", "global_gap")
        # Non-root nodes: global share is relative to the org total, not just their own parent group.
        org_total_potential = sum(max(results[n.id].final_potential, 0) for n in top_level_roots)
        org_total_effort = sum(results[n.id].total_effort for n in top_level_roots)
        for node in nodes:
            if node.parent_id is None:
                continue
            r = results[node.id]
            p_share = (max(r.final_potential, 0) / org_total_potential) if org_total_potential > 0 else None
            e_share = (r.total_effort / org_total_effort) if org_total_effort > 0 else None
            r.global_potential_share = p_share
            r.global_effort_share = e_share
            # Gap is intentionally left None (not infinity) when potential share is
            # zero, even if effort share is nonzero (e.g. negative final_potential
            # clamped to 0) — callers must distinguish "no data" from "zero potential".
            r.global_gap = (e_share / p_share) if (p_share is not None and p_share > 0 and e_share is not None) else None

    return results
