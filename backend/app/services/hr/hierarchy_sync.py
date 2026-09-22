from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode, HrHierarchySync
from app.services import hierarchy as hierarchy_service
from app.services.hr.client import HrApiClient
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
    resolution logic (`_resolve_group`) holds them individually since their
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
    else:
        parent_node_id = hr_id_to_node_id.get(group.parent_id)
        if parent_node_id is None:
            return GroupResolution(
                hr_group_id=group.id, name=group.name, action="held",
                resolved_node_id=None, level=None,
                reason=f"parent group unresolved: {group.parent_id!r}",
            )

    matches = session.execute(
        select(HierarchyNode).where(
            HierarchyNode.parent_id.is_(None) if parent_node_id is None
            else HierarchyNode.parent_id == parent_node_id,
            HierarchyNode.name == group.name,
        )
    ).scalars().all()

    if len(matches) > 1:
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="held",
            resolved_node_id=None, level=None,
            reason=f"ambiguous match: {len(matches)} existing nodes named {group.name!r}",
        )

    if len(matches) == 1:
        existing = matches[0]
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="matched",
            resolved_node_id=existing.id, level=level, reason=None,
        )

    if parent_node_id is not None:
        parent_node = session.get(HierarchyNode, parent_node_id)
        child_rank = hierarchy_service.get_level_rank(session, level)
        parent_rank = (
            hierarchy_service.get_level_rank(session, parent_node.level)
            if parent_node is not None else None
        )
        if parent_node is None or parent_rank is None or child_rank is None or child_rank <= parent_rank:
            parent_level_desc = parent_node.level if parent_node is not None else "<missing>"
            return GroupResolution(
                hr_group_id=group.id, name=group.name, action="held",
                resolved_node_id=None, level=None,
                reason=f"level rank not below parent: {level!r} vs parent's {parent_level_desc!r}",
            )

    node = hierarchy_service.create_node(session, level=level, name=group.name, parent_id=parent_node_id)
    return GroupResolution(
        hr_group_id=group.id, name=group.name, action="created",
        resolved_node_id=node.id, level=level, reason=None,
    )


async def run_hierarchy_sync(session: Session, client: HrApiClient) -> HrHierarchySync:
    run = HrHierarchySync()
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        groups = [group async for group in client.iter_groups()]
        ordered = _topological_order(groups)

        hr_id_to_node_id: dict[str, uuid.UUID] = {}
        results: list[dict[str, Any]] = []
        created = matched = held = 0

        for group in ordered:
            resolution = _resolve_group(session, group, hr_id_to_node_id=hr_id_to_node_id)
            if resolution.resolved_node_id is not None:
                hr_id_to_node_id[group.id] = resolution.resolved_node_id
            if resolution.action == "created":
                created += 1
            elif resolution.action == "matched":
                matched += 1
            else:
                held += 1
            results.append(
                {
                    "hr_group_id": resolution.hr_group_id,
                    "name": resolution.name,
                    "action": resolution.action,
                    "resolved_node_id": str(resolution.resolved_node_id) if resolution.resolved_node_id else None,
                    "level": resolution.level,
                    "reason": resolution.reason,
                }
            )

        run.parsed_state = results
        run.created_count = created
        run.matched_count = matched
        run.held_count = held
        run.status = "completed"
        run.completed_at = datetime.now(tz=timezone.utc)
        session.commit()
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(tz=timezone.utc)
        session.commit()

    return run
