from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyLevelType, HierarchyNode, Soldier


class HierarchyError(Exception):
    """Raised on an invalid hierarchy operation (cycle, guard)."""


def _get_level_rank(session: Session, level_key: str) -> int | None:
    return session.execute(
        select(HierarchyLevelType.rank).where(HierarchyLevelType.key == level_key)
    ).scalar_one_or_none()


def create_node(
    session: Session,
    *,
    level: str,
    name: str,
    parent_id: uuid.UUID | None,
    commander_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> HierarchyNode:
    level_rank = _get_level_rank(session, level)
    if level_rank is None:
        raise HierarchyError(f"unknown level: {level}")
    if parent_id is None:
        parent = None
    else:
        parent = session.get(HierarchyNode, parent_id)
        if parent is None:
            raise HierarchyError("parent not found")
        parent_rank = _get_level_rank(session, parent.level)
        if parent_rank is None or level_rank <= parent_rank:
            raise HierarchyError("child level must rank below parent level")

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
        new_base: list[uuid.UUID] = []
    else:
        if new_parent_id == node_id:
            raise HierarchyError("a node cannot be its own parent")
        parent = session.get(HierarchyNode, new_parent_id)
        if parent is None:
            raise HierarchyError("parent not found")
        if node.id in parent.path_ids:
            raise HierarchyError("cannot move a node under its own descendant")
        node_rank = _get_level_rank(session, node.level)
        parent_rank = _get_level_rank(session, parent.level)
        if node_rank is None or parent_rank is None or node_rank <= parent_rank:
            raise HierarchyError("node level must rank below new parent level")
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
    if commander_id is not None:
        soldier = session.get(Soldier, commander_id)
        if soldier is None:
            raise HierarchyError("commander not found")
        # Clear this soldier as commander from any other node
        session.query(HierarchyNode).filter(
            HierarchyNode.commander_id == soldier.id,
            HierarchyNode.id != node_id,
        ).update({"commander_id": None})
        soldier.hierarchy_node_id = node_id
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


def create_level_type(
    session: Session, *, key: str, label: str, actor_id: uuid.UUID | None = None
) -> HierarchyLevelType:
    existing = session.execute(
        select(HierarchyLevelType.id).where(HierarchyLevelType.key == key)
    ).first()
    if existing is not None:
        raise HierarchyError(f"level type key already exists: {key}")
    max_rank = session.execute(select(func.max(HierarchyLevelType.rank))).scalar_one() or 0
    level_type = HierarchyLevelType(key=key, label=label, rank=max_rank + 1)
    session.add(level_type)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_level_type.create",
        entity_type="hierarchy_level_type",
        entity_id=level_type.id,
        after={"key": key, "label": label, "rank": level_type.rank},
    )
    return level_type


def delete_level_type(
    session: Session, *, id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    level_type = session.get(HierarchyLevelType, id)
    if level_type is None:
        raise HierarchyError("level type not found")
    in_use = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.level == level_type.key).limit(1)
    ).first()
    if in_use is not None:
        raise HierarchyError("cannot delete a level type that is in use")
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_level_type.delete",
        entity_type="hierarchy_level_type",
        entity_id=level_type.id,
        before={"key": level_type.key, "label": level_type.label},
    )
    session.delete(level_type)


def change_node_level(
    session: Session, *, node_id: uuid.UUID, level: str, actor_id: uuid.UUID | None = None
) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    new_rank = _get_level_rank(session, level)
    if new_rank is None:
        raise HierarchyError("unknown level: " + level)

    if node.parent_id is not None:
        parent = session.get(HierarchyNode, node.parent_id)
        parent_rank = _get_level_rank(session, parent.level) if parent else None
        if parent_rank is None or new_rank <= parent_rank:
            raise HierarchyError("invalid_level_for_position")

    children = session.execute(
        select(HierarchyNode).where(HierarchyNode.parent_id == node_id)
    ).scalars().all()
    if children:
        child_ranks = [_get_level_rank(session, c.level) for c in children]
        if any(r is None for r in child_ranks) or new_rank >= min(child_ranks):
            raise HierarchyError("invalid_level_for_position")

    before = {"level": node.level}
    node.level = level
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.change_level",
        entity_type="hierarchy_node",
        entity_id=node.id,
        before=before,
        after={"level": level},
    )
    return node


class ReorderViolation(HierarchyError):
    def __init__(self, violations: list[dict[str, str]]):
        self.violations = violations
        super().__init__("reorder_would_violate_tree")


def reorder_level_types(
    session: Session, *, ordered_ids: list[uuid.UUID], actor_id: uuid.UUID | None = None
) -> list[HierarchyLevelType]:
    all_types = session.execute(select(HierarchyLevelType)).scalars().all()
    if {t.id for t in all_types} != set(ordered_ids) or len(ordered_ids) != len(all_types):
        raise HierarchyError("ordered_ids must contain exactly all existing level type ids")

    new_rank_by_id = {type_id: i + 1 for i, type_id in enumerate(ordered_ids)}
    new_rank_by_key = {t.key: new_rank_by_id[t.id] for t in all_types}
    label_by_key = {t.key: t.label for t in all_types}

    nodes = session.execute(select(HierarchyNode)).scalars().all()
    nodes_by_id = {n.id: n for n in nodes}
    violations: list[dict[str, str]] = []
    for node in nodes:
        if node.parent_id is None:
            continue
        parent = nodes_by_id.get(node.parent_id)
        if parent is None:
            continue
        child_rank = new_rank_by_key.get(node.level)
        parent_rank = new_rank_by_key.get(parent.level)
        if child_rank is None or parent_rank is None:
            continue
        if child_rank <= parent_rank:
            violations.append(
                {
                    "parent": f"{parent.name} ({label_by_key[parent.level]})",
                    "child": f"{node.name} ({label_by_key[node.level]})",
                }
            )
    if violations:
        raise ReorderViolation(violations)

    before = {t.key: t.rank for t in all_types}
    offset = len(all_types) + max(t.rank for t in all_types) + 1
    for t in all_types:
        t.rank = new_rank_by_id[t.id] + offset
    session.flush()
    for t in all_types:
        t.rank = new_rank_by_id[t.id]
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_level_type.reorder",
        entity_type="hierarchy_level_type",
        before={"ranks": before},
        after={"ranks": {t.key: t.rank for t in all_types}},
    )
    return sorted(all_types, key=lambda t: t.rank)
