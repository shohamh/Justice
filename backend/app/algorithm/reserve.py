from __future__ import annotations

import uuid
from collections import deque
from typing import Sequence

from app.algorithm.types import Assignment, DutyBlock, ReserveEntry, SoldierInput


def select_reserves(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    assignments: Sequence[Assignment],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]],
    soldier_node: dict[uuid.UUID, uuid.UUID],
    node_soldiers: dict[uuid.UUID, list[uuid.UUID]],
) -> list[ReserveEntry]:
    duty_map = {d.id: d for d in duties}
    soldier_map = {s.id: s for s in soldiers}
    results: list[ReserveEntry] = []

    for a in assignments:
        duty = duty_map[a.duty_id]
        primary_id = a.soldier_id
        primary_node = soldier_node.get(primary_id)
        if primary_node is None:
            continue

        visited_nodes: set[uuid.UUID] = set()
        queue: deque[tuple[uuid.UUID, int]] = deque()
        queue.append((primary_node, 0))
        visited_nodes.add(primary_node)

        reserve_candidates: list[tuple[uuid.UUID, int]] = []

        while queue:
            node_id, distance = queue.popleft()
            for sid in node_soldiers.get(node_id, []):
                if sid == primary_id:
                    continue
                s = soldier_map.get(sid)
                if s is None:
                    continue
                if duty.duty_type_id in s.exempted_duty_type_ids:
                    continue
                if any(cs <= duty.end_date and ce >= duty.start_date
                       for cs, ce in s.approved_constraint_dates):
                    continue
                overlapping = False
                for other_a in assignments:
                    if other_a.soldier_id == sid:
                        other_duty = duty_map.get(other_a.duty_id)
                        if other_duty and other_duty.start_date <= duty.end_date and other_duty.end_date >= duty.start_date:
                            overlapping = True
                            break
                if overlapping:
                    continue
                reserve_candidates.append((sid, distance))

            parent = hierarchy_parent.get(node_id)
            if parent is not None and parent not in visited_nodes:
                visited_nodes.add(parent)
                for sid in node_soldiers.get(parent, []):
                    if sid == primary_id:
                        continue
                    s = soldier_map.get(sid)
                    if s is None:
                        continue
                    reserve_candidates.append((sid, distance + 1))
                for sibling in hierarchy_children.get(parent, []):
                    if sibling not in visited_nodes:
                        visited_nodes.add(sibling)
                        queue.append((sibling, distance + 1))

        if reserve_candidates:
            reserve_candidates.sort(key=lambda x: x[1])
            best_id, _best_dist = reserve_candidates[0]
            results.append(ReserveEntry(
                duty_id=a.duty_id,
                primary_soldier_id=primary_id,
                reserve_soldier_id=best_id,
            ))

    return results
