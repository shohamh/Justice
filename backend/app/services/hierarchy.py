from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyNode, Soldier

# Top (index 0) to bottom. A child must be at any level below the parent.
LEVEL_ORDER = ["division", "unit", "department", "branch", "group", "team"]


class HierarchyError(Exception):
    """Raised on an invalid hierarchy operation (bad level nesting, cycle, guard)."""


def _validate_child_level(parent_level: str, child_level: str) -> bool:
    """Return True if child_level is any level below parent_level."""
    try:
        return LEVEL_ORDER.index(child_level) > LEVEL_ORDER.index(parent_level)
    except ValueError:
        return False


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
        if level != LEVEL_ORDER[0]:
            raise HierarchyError(f"root nodes must be '{LEVEL_ORDER[0]}'")
        parent = None
    else:
        parent = session.get(HierarchyNode, parent_id)
        if parent is None:
            raise HierarchyError("parent not found")
        if not _validate_child_level(parent.level, level):
            raise HierarchyError(
                f"a {parent.level} cannot contain {level} nodes"
            )

    node = HierarchyNode(
        level=level, name=name, parent_id=parent_id, commander_id=commander_id, path_ids=[]
    )
    session.add(node)
    session.flush()  # populate node.id
    node.path_ids = [*parent.path_ids, node.id] if parent is not None else [node.id]
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


def move_node(
    session: Session,
    *,
    node_id: uuid.UUID,
    new_parent_id: uuid.UUID | None,
    actor_id: uuid.UUID | None = None,
) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")

    if new_parent_id is None:
        if node.level != "department":
            raise HierarchyError("only departments can be roots")
        new_base: list[uuid.UUID] = []
    else:
        if new_parent_id == node_id:
            raise HierarchyError("a node cannot be its own parent")
        parent = session.get(HierarchyNode, new_parent_id)
        if parent is None:
            raise HierarchyError("parent not found")
        if node.id in parent.path_ids:
            raise HierarchyError("cannot move a node under its own descendant")
        if not _validate_child_level(parent.level, node.level):
            raise HierarchyError(
                f"a {parent.level} cannot contain {node.level} nodes"
            )
        new_base = list(parent.path_ids)

    old_path = list(node.path_ids)
    old_prefix_len = len(old_path)  # old_path ends with node.id
    new_node_path = [*new_base, node.id]

    descendants = (
        session.execute(select(HierarchyNode).where(HierarchyNode.path_ids.any(node_id)))  # type: ignore[arg-type]  # SQLAlchemy ARRAY.any() accepts scalar UUID
        .scalars()
        .all()
    )

    before = {"parent_id": str(node.parent_id) if node.parent_id else None}
    node.parent_id = new_parent_id
    for d in descendants:
        d.path_ids = new_node_path + list(d.path_ids[old_prefix_len:])
    node.path_ids = new_node_path
    session.flush()

    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.move",
        entity_type="hierarchy_node",
        entity_id=node.id,
        before=before,
        after={"parent_id": str(new_parent_id) if new_parent_id else None},
    )
    return node


def rename_node(
    session: Session, *, node_id: uuid.UUID, name: str, actor_id: uuid.UUID | None = None
) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    before = {"name": node.name}
    node.name = name
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.rename",
        entity_type="hierarchy_node",
        entity_id=node.id,
        before=before,
        after={"name": name},
    )
    return node


def set_commander(
    session: Session,
    *,
    node_id: uuid.UUID,
    commander_id: uuid.UUID | None,
    actor_id: uuid.UUID | None = None,
) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    if commander_id is not None and session.get(Soldier, commander_id) is None:
        raise HierarchyError("commander not found")
    before = {"commander_id": str(node.commander_id) if node.commander_id else None}
    node.commander_id = commander_id
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.set_commander",
        entity_type="hierarchy_node",
        entity_id=node.id,
        before=before,
        after={"commander_id": str(commander_id) if commander_id else None},
    )
    return node


def delete_node(session: Session, *, node_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> None:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    child = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.parent_id == node_id).limit(1)
    ).first()
    if child is not None:
        raise HierarchyError("cannot delete a node that has children")
    soldier = session.execute(
        select(Soldier.id).where(Soldier.hierarchy_node_id == node_id).limit(1)
    ).first()
    if soldier is not None:
        raise HierarchyError("cannot delete a node that has soldiers assigned")
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.delete",
        entity_type="hierarchy_node",
        entity_id=node.id,
        before={"name": node.name, "level": node.level},
    )
    session.delete(node)
