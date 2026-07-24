from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, HierarchyNode, Soldier


def commander_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct commander from the soldier's own node up to the root of
    the hierarchy, excluding the soldier themself if they command their own node.

    Ordered NEAREST-commander-first: chain[0] is the closest ancestor (or the
    soldier's own node) that has a commander, and the list walks outward to
    the root from there. `node.path_ids` is materialized root-first (see
    `hierarchy.py`: `node.path_ids = [*parent.path_ids, node.id]`), so we
    reorder via `reversed(node.path_ids)` rather than relying on the `IN (...)`
    query's row order, which SQL does not guarantee to match the list order.

    Moved here (from app/services/swaps.py) so every request type — not just
    swaps — can share it without importing swaps.py.
    """
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    nodes_by_id = {
        n.id: n
        for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node.path_ids))
        ).scalars().all()
    }
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for node_id in reversed(node.path_ids):
        n = nodes_by_id.get(node_id)
        if n is None:
            continue
        if n.commander_id and n.commander_id != soldier_id and n.commander_id not in seen:
            seen.add(n.commander_id)
            chain.append(n.commander_id)
    return chain


def duty_manager_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct duty manager whose DutyManagerScope covers the soldier's
    node or one of its ancestors — nearest-scope-first, mirroring
    commander_chain_for_soldier's walk. A single node can have more than one
    duty manager scoped to it (unlike commander_id, which is 0-or-1); within
    one node's group, order by full_name for determinism (no other natural
    order exists at that granularity)."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    scopes = session.execute(
        select(DutyManagerScope).where(DutyManagerScope.hierarchy_node_id.in_(node.path_ids))
    ).scalars().all()
    by_node: dict[uuid.UUID, list[uuid.UUID]] = {}
    for s in scopes:
        by_node.setdefault(s.hierarchy_node_id, []).append(s.duty_manager_id)
    dm_ids_needing_names = {dm_id for ids in by_node.values() for dm_id in ids}
    names_by_id = {
        s.id: s.full_name
        for s in session.execute(
            select(Soldier).where(Soldier.id.in_(dm_ids_needing_names))
        ).scalars().all()
    } if dm_ids_needing_names else {}
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for node_id in reversed(node.path_ids):
        for dm_id in sorted(by_node.get(node_id, []), key=lambda i: names_by_id.get(i, "")):
            if dm_id not in seen:
                seen.add(dm_id)
                chain.append(dm_id)
    return chain


def nearest_commander_for_soldier(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = commander_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None


def nearest_duty_manager_for_soldier(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = duty_manager_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None
