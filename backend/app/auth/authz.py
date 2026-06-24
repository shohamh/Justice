from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, HierarchyNode, Soldier
from app.services.eligibility import RANKS_RASAN_AND_ABOVE

PRIVATE_FIELD_NAMES: frozenset[str] = frozenset({"gender", "phone", "email"})


class Action:
    SOLDIER_CREATE = "soldier.create"
    SOLDIER_READ = "soldier.read"
    SOLDIER_UPDATE = "soldier.update"
    SOLDIER_RESET_PASSWORD = "soldier.reset_password"
    SOLDIER_DELETE = "soldier.delete"
    SOLDIER_ASSIGN_ROLE = "soldier.assign_role"
    HIERARCHY_READ = "hierarchy.read"
    HIERARCHY_MANAGE = "hierarchy.manage"
    HIERARCHY_LEVEL_TYPE_MANAGE = "hierarchy.level_type_manage"
    EXEMPTION_GRANT = "exemption.grant"
    EXEMPTION_READ = "exemption.read"
    CONSTRAINT_SUBMIT = "constraint.submit"
    CONSTRAINT_READ = "constraint.read"
    CONSTRAINT_APPROVE = "constraint.approve"
    ASSIGNMENT_MANAGE = "assignment.manage"
    SCORE_ADJUST = "score.adjust"
    ALGORITHM_RUN = "algorithm.run"
    SWAP_APPROVE = "swap.approve"
    ENROLLMENT_APPROVE = "enrollment.approve"
    DM_SCOPE_MANAGE = "dm_scope.manage"
    SHIFT_MANAGE = "shift.manage"


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
    Action.SWAP_APPROVE,
    Action.ASSIGNMENT_MANAGE,
    Action.SCORE_ADJUST,
    Action.ENROLLMENT_APPROVE,
}
_COMMANDER_ACTIONS = {
    Action.SOLDIER_READ,
    Action.HIERARCHY_READ,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.SWAP_APPROVE,
    Action.ENROLLMENT_APPROVE,
}

_DM_GLOBAL_ACTIONS = {
    Action.ALGORITHM_RUN,
    Action.SHIFT_MANAGE,
    Action.HIERARCHY_LEVEL_TYPE_MANAGE,
}


def scope_root_ids(session: Session, user: Soldier) -> set[uuid.UUID]:
    """The node ids whose subtrees this user governs."""
    roots: set[uuid.UUID] = set()
    if user.role == "duty_manager":
        dm_nodes = (
            session.execute(
                select(DutyManagerScope.hierarchy_node_id).where(
                    DutyManagerScope.duty_manager_id == user.id
                )
            )
            .scalars()
            .all()
        )
        roots.update(dm_nodes)
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
        return True
    if user.role == "duty_manager":
        if action in _DM_GLOBAL_ACTIONS:
            return True
        return action in _DM_ACTIONS and _node_in_scope(target_node, roots)
    if user.role == "commander":
        if action == Action.DM_SCOPE_MANAGE:
            return (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            )
        return action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots)
    return False


def can_see_private(session: Session, viewer: Soldier, target: Soldier) -> bool:
    """Return True iff viewer may read private fields on target's record."""
    if viewer.id == target.id:
        return True
    if viewer.role == "admin":
        return False
    if viewer.role in ("duty_manager", "commander"):
        roots = scope_root_ids(session, viewer)
        node = session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
        return _node_in_scope(node, roots)
    return False


def authorize(
    session: Session, user: Soldier, action: str, *, target_node: HierarchyNode | None
) -> None:
    """Raise 403 unless `user` may perform `action` against `target_node`'s subtree."""
    roots = scope_root_ids(session, user)
    if not can(user, action, target_node=target_node, roots=roots):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
