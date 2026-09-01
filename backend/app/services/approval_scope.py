from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, HierarchyLevelType, HierarchyNode, Soldier

UNIT_JOIN_DATE_COMMANDER_MIN_LEVEL_KEY = "group"  # seeded key for מדור
UNIT_JOIN_DATE_DUTY_MANAGER_MIN_LEVEL_KEY = "branch"  # seeded key for ענף


def unit_join_date_stage_authorized(
    session: Session, *, actor: Soldier, target_node: HierarchyNode | None, stage: str,
) -> bool:
    if stage not in {"commander", "duty_manager"}:
        return False
    if actor.role == "admin":
        return True
    if target_node is None:
        return False
    from app.auth.authz import commanded_node_ids, dm_scope_node_ids
    roots = (
        commanded_node_ids(session, actor.id)
        if stage == "commander" else dm_scope_node_ids(session, actor.id)
    )
    required_level_key = (
        UNIT_JOIN_DATE_COMMANDER_MIN_LEVEL_KEY
        if stage == "commander" else UNIT_JOIN_DATE_DUTY_MANAGER_MIN_LEVEL_KEY
    )
    from app.services.authority import dm_scope_covers_target
    return dm_scope_covers_target(
        session, scope_root_ids=set(roots), target_node=target_node,
        required_level_key=required_level_key,
    )


def unit_join_date_initiator_authorized(session: Session, *, actor: Soldier, target: Soldier) -> bool:
    if actor.id == target.id:
        return True
    target_node = session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
    return any(unit_join_date_stage_authorized(session, actor=actor, target_node=target_node, stage=stage) for stage in ("commander", "duty_manager"))


class UnitJoinDateEditScope:
    """Precompute the two approval scopes used by roster edit affordances."""

    __slots__ = ("is_admin", "actor_id", "_commander_roots", "_duty_manager_roots")

    def __init__(self, session: Session, *, actor: Soldier) -> None:
        self.is_admin = actor.role == "admin"
        self.actor_id = actor.id
        self._commander_roots: set[uuid.UUID] = set()
        self._duty_manager_roots: set[uuid.UUID] = set()
        if self.is_admin:
            return
        from app.auth.authz import commanded_node_ids, dm_scope_node_ids

        level_ranks = {
            row.key: row.rank for row in session.execute(select(HierarchyLevelType)).scalars()
        }
        commander_min = level_ranks.get(UNIT_JOIN_DATE_COMMANDER_MIN_LEVEL_KEY)
        duty_manager_min = level_ranks.get(UNIT_JOIN_DATE_DUTY_MANAGER_MIN_LEVEL_KEY)
        if commander_min is not None:
            self._commander_roots = {
                node_id for node_id in commanded_node_ids(session, actor.id)
                if (node := session.get(HierarchyNode, node_id)) is not None
                and level_ranks.get(node.level) is not None
                and level_ranks[node.level] <= commander_min
            }
        if duty_manager_min is not None:
            self._duty_manager_roots = {
                node_id for node_id in dm_scope_node_ids(session, actor.id)
                if (node := session.get(HierarchyNode, node_id)) is not None
                and level_ranks.get(node.level) is not None
                and level_ranks[node.level] <= duty_manager_min
            }

    def authorized(self, *, actor: Soldier, target: Soldier, target_node: HierarchyNode | None) -> bool:
        if actor.id == target.id or self.is_admin:
            return True
        if target_node is None:
            return False
        return any(root in target_node.path_ids for root in self._commander_roots | self._duty_manager_roots)


def commander_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct commander from the soldier's own node up to the root of
    the hierarchy, excluding the soldier themself if they command their own node.

    Ordered NEAREST-commander-first: chain[0] is the closest ancestor (or the
    soldier's own node) that has a commander, and the list walks outward to
    the root from there. `node.path_ids` is materialized root-first (see
    `hierarchy.py`: `node.path_ids = [*parent.path_ids, node.id]`), so we
    reorder via `reversed(node.path_ids)` rather than relying on the `IN (...)`
    query's row order, which SQL does not guarantee to match the list order.

    Moved here (from app/services/swaps.py) so every request type — not just
    swaps — can share it without importing swaps.py.
    """
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    nodes_by_id = {
        n.id: n
        for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node.path_ids))
        ).scalars().all()
    }
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for node_id in reversed(node.path_ids):
        n = nodes_by_id.get(node_id)
        if n is None:
            continue
        if n.commander_id and n.commander_id != soldier_id and n.commander_id not in seen:
            seen.add(n.commander_id)
            chain.append(n.commander_id)
    return chain


def duty_manager_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct duty manager whose DutyManagerScope covers the soldier's
    node or one of its ancestors — nearest-scope-first, mirroring
    commander_chain_for_soldier's walk. A single node can have more than one
    duty manager scoped to it (unlike commander_id, which is 0-or-1); within
    one node's group, order by full_name for determinism (no other natural
    order exists at that granularity)."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    scopes = session.execute(
        select(DutyManagerScope).where(DutyManagerScope.hierarchy_node_id.in_(node.path_ids))
    ).scalars().all()
    by_node: dict[uuid.UUID, list[uuid.UUID]] = {}
    for s in scopes:
        by_node.setdefault(s.hierarchy_node_id, []).append(s.duty_manager_id)
    dm_ids_needing_names = {dm_id for ids in by_node.values() for dm_id in ids}
    names_by_id = {
        s.id: s.full_name
        for s in session.execute(
            select(Soldier).where(Soldier.id.in_(dm_ids_needing_names))
        ).scalars().all()
    } if dm_ids_needing_names else {}
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for node_id in reversed(node.path_ids):
        for dm_id in sorted(by_node.get(node_id, []), key=lambda i: names_by_id.get(i, "")):
            if dm_id not in seen:
                seen.add(dm_id)
                chain.append(dm_id)
    return chain


def nearest_commander_for_soldier(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = commander_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None


def nearest_duty_manager_for_soldier(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = duty_manager_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None


def unit_join_date_approver_chain(
    session: Session, soldier_id: uuid.UUID, *, stage: str,
) -> list[uuid.UUID]:
    """Return nearest-first approvers who can actually approve this stage.

    The raw hierarchy/scope chains are also used for visibility and notification
    cascades. Unit-join-date approvals require the stricter Medor/Anaph scope,
    so filter those chains through the same authorization predicate used by the
    approval endpoint before selecting a recipient.
    """
    if stage == "commander":
        chain = commander_chain_for_soldier(session, soldier_id)
    elif stage == "duty_manager":
        chain = duty_manager_chain_for_soldier(session, soldier_id)
    else:
        return []
    soldier = session.get(Soldier, soldier_id)
    target_node = (
        session.get(HierarchyNode, soldier.hierarchy_node_id)
        if soldier is not None and soldier.hierarchy_node_id else None
    )
    if target_node is None:
        return []
    actors = {
        actor.id: actor
        for actor in session.execute(select(Soldier).where(Soldier.id.in_(chain))).scalars()
    }
    return [
        actor_id for actor_id in chain
        if (actor := actors.get(actor_id)) is not None
        and unit_join_date_stage_authorized(
            session, actor=actor, target_node=target_node, stage=stage,
        )
    ]


def nearest_unit_join_date_approver(
    session: Session, soldier_id: uuid.UUID, *, stage: str,
) -> uuid.UUID | None:
    chain = unit_join_date_approver_chain(session, soldier_id, stage=stage)
    return chain[0] if chain else None


def exemption_approval_flags(
    session: Session, viewer: Soldier, target_node: HierarchyNode | None
) -> tuple[bool, bool]:
    """Mirror the authorization checks in approve_exemption_request_commander_step
    and approve_exemption_request_duty_manager_step, so pending-list responses
    (and, for a notified recipient, the notification's target tab) can tell
    whether `viewer` would actually be allowed to approve, instead of relying
    on the wider notification-cascade scope, which includes visibility-only
    recipients.

    Commander-step mirrors `authorize(session, user, Action.CONSTRAINT_APPROVE, ...)`
    exactly via `can()` — note CONSTRAINT_APPROVE is in both _DM_ACTIONS and
    _COMMANDER_ACTIONS, so an in-scope duty manager (not just a commander) can
    also successfully call approve-commander; using a bare `is_commander(...)`
    check here would produce a false negative (hide a button that would actually
    succeed) for that case.

    Moved here (from app/routes/exemption_requests.py) so both the pending-list
    route and the notification cascade (which needs to know, per notified
    recipient, whether they can actually act) can share one definition.
    """
    from app.auth.authz import Action, can, is_commander, is_duty_manager, scope_root_ids
    from app.services.authority import (
        REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY, dm_scope_covers_target, senior_commander_approval_authorized,
    )

    if viewer.role == "admin":
        return True, True
    roots = scope_root_ids(session, viewer)
    viewer_is_commander = is_commander(session, viewer.id)
    viewer_is_duty_manager = is_duty_manager(session, viewer.id)
    can_commander_step = senior_commander_approval_authorized(
        session, user=viewer, target_node=target_node,
    ) or (viewer_is_duty_manager and can(
        viewer, Action.CONSTRAINT_APPROVE, target_node=target_node, roots=roots,
        is_commander=viewer_is_commander, is_duty_manager=viewer_is_duty_manager,
    ))
    can_dm_step = viewer_is_duty_manager and dm_scope_covers_target(
        session, scope_root_ids=roots, target_node=target_node,
        required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
    )
    return can_commander_step, can_dm_step
