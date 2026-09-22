from __future__ import annotations

from app.services.hr.schemas import HrGroup

# HR's Group.kind -> Justice HierarchyLevelType.key. Unmapped kinds (and
# mapped keys that aren't currently configured in HierarchyLevelType) hold
# the group for review rather than guessing.
# TODO: placeholder kind strings, unconfirmed against real HR API data.
HR_GROUP_KIND_TO_LEVEL_MAP: dict[str, str] = {
    "unit": "unit",
    "department": "department",
    "branch": "branch",
    "mador": "group",
    "team": "team",
}


def _topological_order(groups: list[HrGroup]) -> list[HrGroup]:
    """Order groups so every group appears after its parent (by HR group
    id), when that's determinable. A dangling parent reference or a cycle
    among the remaining groups doesn't raise — those groups are appended
    at the end in their original relative order, and the per-group
    resolution logic (added in Task 3) holds them individually since their
    parent will never appear in the resolved-node map."""
    resolved_ids: set[str] = set()
    ordered: list[HrGroup] = []
    remaining = list(groups)
    while remaining:
        progressed = False
        still_remaining: list[HrGroup] = []
        for group in remaining:
            if group.parent_id is None or group.parent_id in resolved_ids:
                ordered.append(group)
                resolved_ids.add(group.id)
                progressed = True
            else:
                still_remaining.append(group)
        remaining = still_remaining
        if not progressed:
            ordered.extend(remaining)
            break
    return ordered
