from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from app.algorithm.types import DutyBlock, ReserveLink, SoldierInput


def _node_ancestors(node_id: uuid.UUID, hierarchy_parent: dict[uuid.UUID, uuid.UUID | None]) -> set[uuid.UUID]:
    """All ancestor node IDs including node_id itself."""
    path: set[uuid.UUID] = set()
    current: uuid.UUID | None = node_id
    while current is not None:
        if current in path:
            break  # cycle guard
        path.add(current)
        current = hierarchy_parent.get(current)
    return path


def _build_ancestor_cache(
    nodes: set[uuid.UUID],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
) -> dict[uuid.UUID, frozenset[uuid.UUID]]:
    """Pre-compute ancestor sets for all nodes once.

    compute_reserve_dist calls _hierarchy_distance O(R×S×P) times against
    the same ~200 unique nodes.  Building this cache once and reusing it
    cuts ancestor traversals from millions to O(unique_nodes).
    """
    return {n: frozenset(_node_ancestors(n, hierarchy_parent)) for n in nodes}


def _hierarchy_distance(node_a: uuid.UUID, node_b: uuid.UUID,
                        hierarchy_parent: dict[uuid.UUID, uuid.UUID | None]) -> int:
    """Symmetric-difference distance: len(ancestors(a) Δ ancestors(b))."""
    return len(_node_ancestors(node_a, hierarchy_parent).symmetric_difference(
        _node_ancestors(node_b, hierarchy_parent)
    ))


def _hierarchy_distance_cached(
    node_a: uuid.UUID,
    node_b: uuid.UUID,
    ancestor_cache: dict[uuid.UUID, frozenset[uuid.UUID]],
) -> int:
    """Fast variant using a pre-built ancestor cache."""
    return len(ancestor_cache[node_a].symmetric_difference(ancestor_cache[node_b]))


def link_reserves(
    primary_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]],
    reserve_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]],
    soldier_node: dict[uuid.UUID, uuid.UUID],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]],
) -> list[ReserveLink]:
    """For each primary assignment, find the closest reserve (by hierarchy distance)
    in the same shift. One reserve may cover multiple primaries.

    Args:
        primary_assignments: list of (assignment_id, soldier_id, shift_id)
        reserve_assignments: list of (assignment_id, soldier_id, shift_id)
        soldier_node, hierarchy_parent, hierarchy_children: from build_hierarchy_maps
    Returns:
        list of ReserveLink — one per primary assignment that has a reserve in its shift
    """
    reserves_by_shift: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]] = {}
    for r_assign_id, r_soldier_id, shift_id in reserve_assignments:
        reserves_by_shift.setdefault(shift_id, []).append((r_assign_id, r_soldier_id))

    all_nodes: set[uuid.UUID] = set(soldier_node.values())
    ancestor_cache = _build_ancestor_cache(all_nodes, hierarchy_parent)

    links: list[ReserveLink] = []
    for p_assign_id, p_soldier_id, shift_id in primary_assignments:
        candidates = reserves_by_shift.get(shift_id)
        if not candidates:
            continue
        p_node = soldier_node.get(p_soldier_id)
        if p_node is None:
            r_assign_id, _ = candidates[0]
            links.append(ReserveLink(
                reserve_assignment_id=r_assign_id,
                primary_assignment_id=p_assign_id,
                hierarchy_distance=10,
            ))
            continue

        best_assign_id: uuid.UUID | None = None
        best_dist = 999
        for r_assign_id, r_soldier_id in candidates:
            r_node = soldier_node.get(r_soldier_id)
            if r_node is None:
                dist = 10
            elif r_node in ancestor_cache and p_node in ancestor_cache:
                dist = _hierarchy_distance_cached(p_node, r_node, ancestor_cache)
            else:
                dist = _hierarchy_distance(p_node, r_node, hierarchy_parent)
            if dist < best_dist:
                best_dist = dist
                best_assign_id = r_assign_id

        if best_assign_id is not None:
            links.append(ReserveLink(
                reserve_assignment_id=best_assign_id,
                primary_assignment_id=p_assign_id,
                hierarchy_distance=best_dist,
            ))

    return links


def compute_reserve_dist(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    block_to_shift: dict[uuid.UUID, uuid.UUID],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
    soldier_node: dict[uuid.UUID, uuid.UUID],
) -> dict[tuple[int, int], int]:
    """Precompute hierarchy distance from each candidate reserve soldier to the
    nearest primary-eligible soldier for the same shift.

    Returns dict mapping (duty_index, soldier_index) -> int distance,
    populated only for reserve blocks.
    """
    duty_list = list(duties)
    soldier_list = list(soldiers)

    shift_primary_nodes: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for d in duty_list:
        if not d.is_reserve:
            shift_id = block_to_shift.get(d.id)
            if shift_id is not None:
                for s in soldier_list:
                    node = soldier_node.get(s.id)
                    if node:
                        shift_primary_nodes[shift_id].add(node)

    # Pre-build ancestor sets for all unique node IDs so the inner distance
    # loop doesn't recompute O(depth) traversals millions of times.
    all_nodes: set[uuid.UUID] = set(soldier_node.values())
    ancestor_cache = _build_ancestor_cache(all_nodes, hierarchy_parent)

    result: dict[tuple[int, int], int] = {}
    for di, d in enumerate(duty_list):
        if not d.is_reserve:
            continue
        shift_id = block_to_shift.get(d.id)
        primary_nodes = shift_primary_nodes.get(shift_id, set()) if shift_id else set()
        for si, s in enumerate(soldier_list):
            s_node = soldier_node.get(s.id)
            if s_node is None or not primary_nodes:
                result[(di, si)] = 10
            else:
                result[(di, si)] = min(
                    _hierarchy_distance_cached(s_node, pn, ancestor_cache)
                    for pn in primary_nodes
                    if pn in ancestor_cache
                )
    return result
