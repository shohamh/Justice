from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyNode

# Top (index 0) to bottom. A node's parent must be exactly one level above it.
LEVEL_ORDER = ["department", "branch", "group", "team"]


class HierarchyError(Exception):
    """Raised on an invalid hierarchy operation (bad level nesting, cycle, guard)."""


def _expected_child_level(parent_level: str) -> str | None:
    i = LEVEL_ORDER.index(parent_level)
    return LEVEL_ORDER[i + 1] if i + 1 < len(LEVEL_ORDER) else None


def create_node(
    session: Session,
    *,
    level: str,
    name: str,
    parent_id: uuid.UUID | None,
    commander_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> HierarchyNode:
    if level not in LEVEL_ORDER:
        raise HierarchyError(f"unknown level: {level}")
    if parent_id is None:
        if level != "department":
            raise HierarchyError("root nodes must be 'department'")
        parent = None
    else:
        parent = session.get(HierarchyNode, parent_id)
        if parent is None:
            raise HierarchyError("parent not found")
        if _expected_child_level(parent.level) != level:
            raise HierarchyError(f"a {parent.level} can only contain {_expected_child_level(parent.level)} nodes")

    node = HierarchyNode(level=level, name=name, parent_id=parent_id, commander_id=commander_id, path_ids=[])
    session.add(node)
    session.flush()  # populate node.id
    node.path_ids = ([*parent.path_ids, node.id] if parent is not None else [node.id])
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.create",
        entity_type="hierarchy_node",
        entity_id=node.id,
        after={"level": level, "name": name, "parent_id": str(parent_id) if parent_id else None},
    )
    return node
