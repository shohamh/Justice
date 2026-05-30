from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode, Soldier


class Action:
    SOLDIER_CREATE = "soldier.create"
    SOLDIER_READ = "soldier.read"
    SOLDIER_UPDATE = "soldier.update"
    SOLDIER_RESET_PASSWORD = "soldier.reset_password"
    SOLDIER_DELETE = "soldier.delete"
    SOLDIER_ASSIGN_ROLE = "soldier.assign_role"
    HIERARCHY_READ = "hierarchy.read"
    HIERARCHY_MANAGE = "hierarchy.manage"
    EXEMPTION_GRANT = "exemption.grant"
    EXEMPTION_READ = "exemption.read"
    CONSTRAINT_SUBMIT = "constraint.submit"
    CONSTRAINT_READ = "constraint.read"
    CONSTRAINT_APPROVE = "constraint.approve"
    ASSIGNMENT_MANAGE = "assignment.manage"
    SCORE_ADJUST = "score.adjust"
    ALGORITHM_RUN = "algorithm.run"


_DM_ACTIONS = {
    Action.SOLDIER_CREATE,
    Action.SOLDIER_READ,
    Action.SOLDIER_UPDATE,
    Action.SOLDIER_RESET_PASSWORD,
    Action.SOLDIER_DELETE,
    Action.HIERARCHY_READ,
    Action.HIERARCHY_MANAGE,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.ASSIGNMENT_MANAGE,
    Action.SCORE_ADJUST,
    Action.ALGORITHM_RUN,
}
_COMMANDER_ACTIONS = {
    Action.SOLDIER_READ,
    Action.HIERARCHY_READ,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
}

_DM_GLOBAL_ACTIONS = {
    Action.ALGORITHM_RUN,
}


def scope_root_ids(session: Session, user: Soldier) -> set[uuid.UUID]:
    """The node ids whose subtrees this user governs.

    - duty_manager: their own assigned node.
    - commander: every node where they are the commander.
    - admin / soldier: none (admin is global; soldier has no scope).
    """
    roots: set[uuid.UUID] = set()
    if user.role == "duty_manager" and user.hierarchy_node_id is not None:
        roots.add(user.hierarchy_node_id)
    commanded = (
        session.execute(select(HierarchyNode.id).where(HierarchyNode.commander_id == user.id))
        .scalars()
        .all()
    )
    roots.update(commanded)
    return roots


def _node_in_scope(target_node: HierarchyNode | None, roots: set[uuid.UUID]) -> bool:
    if target_node is None:
        return False
    return any(r in target_node.path_ids for r in roots)


def can(
    user: Soldier,
    action: str,
    *,
    target_node: HierarchyNode | None,
    roots: set[uuid.UUID],
) -> bool:
    if user.role == "admin":
        return True  # admin: account/role/hierarchy authority, global
    if user.role == "duty_manager":
        if action in _DM_GLOBAL_ACTIONS:
            return True  # no node-scoping for global DM actions
        return action in _DM_ACTIONS and _node_in_scope(target_node, roots)
    if user.role == "commander":
        return action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots)
    return False  # plain soldier: management actions denied (self-reads handled at the route)


def authorize(
    session: Session, user: Soldier, action: str, *, target_node: HierarchyNode | None
) -> None:
    """Raise 403 unless `user` may perform `action` against `target_node`'s subtree."""
    roots = scope_root_ids(session, user)
    if not can(user, action, target_node=target_node, roots=roots):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
