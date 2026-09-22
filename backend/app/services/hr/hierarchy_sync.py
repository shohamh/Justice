from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode
from app.services import hierarchy as hierarchy_service
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


@dataclass(frozen=True)
class GroupResolution:
    hr_group_id: str
    name: str
    action: str  # "matched" | "created" | "held"
    resolved_node_id: uuid.UUID | None
    level: str | None
    reason: str | None


def _resolve_group(
    session: Session,
    group: HrGroup,
    *,
    hr_id_to_node_id: dict[str, uuid.UUID],
) -> GroupResolution:
    level = HR_GROUP_KIND_TO_LEVEL_MAP.get(group.kind) if group.kind else None
    if level is None:
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="held",
            resolved_node_id=None, level=None,
            reason=f"unmappable kind: {group.kind!r}",
        )
    if hierarchy_service.get_level_rank(session, level) is None:
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="held",
            resolved_node_id=None, level=None,
            reason=f"level not configured in Justice: {level!r}",
        )

    if group.parent_id is None:
        parent_node_id: uuid.UUID | None = None
        existing = session.execute(
            select(HierarchyNode).where(
                HierarchyNode.parent_id.is_(None), HierarchyNode.name == group.name
            )
        ).scalar_one_or_none()
    else:
        parent_node_id = hr_id_to_node_id.get(group.parent_id)
        if parent_node_id is None:
            return GroupResolution(
                hr_group_id=group.id, name=group.name, action="held",
                resolved_node_id=None, level=None,
                reason=f"parent group unresolved: {group.parent_id!r}",
            )
        existing = session.execute(
            select(HierarchyNode).where(
                HierarchyNode.parent_id == parent_node_id, HierarchyNode.name == group.name
            )
        ).scalar_one_or_none()

    if existing is not None:
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="matched",
            resolved_node_id=existing.id, level=level, reason=None,
        )

    node = hierarchy_service.create_node(session, level=level, name=group.name, parent_id=parent_node_id)
    return GroupResolution(
        hr_group_id=group.id, name=group.name, action="created",
        resolved_node_id=node.id, level=level, reason=None,
    )
