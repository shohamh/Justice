from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, HierarchyNode, Soldier
from app.services.eligibility import RANKS_RASAN_AND_ABOVE

PRIVATE_FIELD_NAMES: frozenset[str] = frozenset({"gender", "phone", "email"})


def is_commander(session: Session, soldier_id: uuid.UUID) -> bool:
    """True iff this soldier currently commands at least one hierarchy node."""
    return (
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.commander_id == soldier_id).limit(1)
        ).first()
        is not None
    )


def is_duty_manager(session: Session, soldier_id: uuid.UUID) -> bool:
    """True iff this soldier currently holds at least one DutyManagerScope row."""
    return (
        session.execute(
            select(DutyManagerScope.id)
            .where(DutyManagerScope.duty_manager_id == soldier_id)
            .limit(1)
        ).first()
        is not None
    )


class Action:
    SOLDIER_CREATE = "soldier.create"
    SOLDIER_READ = "soldier.read"
    SOLDIER_UPDATE = "soldier.update"
    SOLDIER_RESET_PASSWORD = "soldier.reset_password"
    SOLDIER_DELETE = "soldier.delete"
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
    HIERARCHY_TRANSFER = "hierarchy.transfer"
    DM_SCOPE_MANAGE = "dm_scope.manage"
    SHIFT_MANAGE = "shift.manage"
    POTENTIAL_READ = "potential.read"
    POTENTIAL_MODIFIER_MANAGE = "potential.modifier_manage"
    MILITARY_LICENSE_DECIDE = "military_license.decide"
    RANGE_MANAGE = "range.manage"


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
    Action.POTENTIAL_READ,
    Action.POTENTIAL_MODIFIER_MANAGE,
    Action.MILITARY_LICENSE_DECIDE,
    Action.HIERARCHY_TRANSFER,
    Action.RANGE_MANAGE,
}
_COMMANDER_ACTIONS = {
    Action.SOLDIER_READ,
    Action.HIERARCHY_READ,
    # I-1: commanders may manage the hierarchy subtree they directly command
    # (add/rename/move/delete child nodes, assign commanders, etc.), scoped
    # via _node_in_scope like every other action here — since roots already
    # includes commanded node ids (see scope_root_ids) and _node_in_scope
    # matches via path_ids containment, this covers descendants of the
    # commanded node too, mirroring how duty-manager scope already works.
    Action.HIERARCHY_MANAGE,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.SWAP_APPROVE,
    Action.ENROLLMENT_APPROVE,
    Action.HIERARCHY_TRANSFER,
}

_DM_GLOBAL_ACTIONS = {
    Action.ALGORITHM_RUN,
    Action.SHIFT_MANAGE,
    Action.HIERARCHY_LEVEL_TYPE_MANAGE,
}


def scope_root_ids(session: Session, user: Soldier) -> set[uuid.UUID]:
    """The node ids whose subtrees this user governs."""
    roots: set[uuid.UUID] = set()
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
    is_commander: bool,
    is_duty_manager: bool,
) -> bool:
    if user.role == "admin":
        return True
    allowed = False
    if is_duty_manager:
        if action in _DM_GLOBAL_ACTIONS:
            return True
        if action in _DM_ACTIONS and _node_in_scope(target_node, roots):
            allowed = True
    if is_commander:
        if action in (Action.POTENTIAL_READ, Action.POTENTIAL_MODIFIER_MANAGE):
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action == Action.DM_SCOPE_MANAGE:
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action == Action.MILITARY_LICENSE_DECIDE:
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots):
            allowed = True
    return allowed


def can_see_private_node(session: Session, viewer: Soldier, node: HierarchyNode | None) -> bool:
    """Return True iff viewer's commander/duty-manager scope covers `node`.

    Deliberately does not grant admins a blanket bypass here: seeing another
    soldier's private fields (exemption reasons, contact info) requires being
    in-scope as a commander or duty manager, same as anyone else. An admin
    who is *also* a commander still qualifies via that scope.
    """
    if is_commander(session, viewer.id) or is_duty_manager(session, viewer.id):
        roots = scope_root_ids(session, viewer)
        return _node_in_scope(node, roots)
    return False


def can_see_private(session: Session, viewer: Soldier, target: Soldier) -> bool:
    """Return True iff viewer may read private fields on target's record."""
    if viewer.id == target.id:
        return True
    node = session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
    return can_see_private_node(session, viewer, node)


def can_view_medical_document(session: Session, viewer: Soldier, target: Soldier) -> bool:
    """Stricter than can_see_private: viewing the medical DOCUMENT itself (not just
    the exemption's other fields) requires the viewer be a commander at or above a
    configured minimum level in the target's own command chain, or a duty manager
    at or above a separate configured minimum level in their scope over that chain.
    Plain scope containment (as can_see_private_node checks) is not enough.
    """
    if viewer.id == target.id:
        return True
    node = session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
    if node is None:
        return False

    from app.services.authority import dm_scope_covers_target
    from app.services.settings_loader import SettingNotFound, get_setting

    def _min_level(key: str, default_level: str) -> str:
        try:
            value = get_setting(session, key)
            return str(value) if value else default_level
        except SettingNotFound:
            return default_level

    if is_commander(session, viewer.id):
        commander_roots = set(
            session.execute(
                select(HierarchyNode.id).where(HierarchyNode.commander_id == viewer.id)
            )
            .scalars()
            .all()
        )
        required_level = _min_level("exemptions.medical_doc_min_commander_level", "מדור")
        if dm_scope_covers_target(
            session, scope_root_ids=commander_roots, target_node=node, required_level_key=required_level
        ):
            return True
    if is_duty_manager(session, viewer.id):
        dm_roots = set(
            session.execute(
                select(DutyManagerScope.hierarchy_node_id).where(
                    DutyManagerScope.duty_manager_id == viewer.id
                )
            )
            .scalars()
            .all()
        )
        required_level = _min_level("exemptions.medical_doc_min_duty_manager_level", "מרכז")
        if dm_scope_covers_target(
            session, scope_root_ids=dm_roots, target_node=node, required_level_key=required_level
        ):
            return True
    return False


def authorize(
    session: Session, user: Soldier, action: str, *, target_node: HierarchyNode | None
) -> None:
    """Raise 403 unless `user` may perform `action` against `target_node`'s subtree."""
    roots = scope_root_ids(session, user)
    if not can(
        user,
        action,
        target_node=target_node,
        roots=roots,
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def forbid_self_target(user: Soldier, target_soldier_id: uuid.UUID) -> None:
    """Raise 403 if `user` is attempting to decide (approve/reject) their own request.

    Approval-style actions rely on scope containment (`_node_in_scope`), which does
    not by itself exclude the requester deciding their own request — a commander's
    own hierarchy node is typically inside their own commanded subtree. This is an
    explicit segregation-of-duties check layered on top of `authorize()`, and it
    applies even to admins.
    """
    if user.id == target_soldier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="cannot_act_on_own_request")
