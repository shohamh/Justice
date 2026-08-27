# backend/app/services/authority.py
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode, Soldier
from app.services.hierarchy import get_level_rank
from app.services.settings_loader import SettingNotFound, get_setting, get_setting_int

REQUEST_CANCELLATION_COMMANDER_MIN_LEVEL_KEY = "group"
# ^ get_level_rank matches HierarchyLevelType.key, not .label — the seed
# migration (alembic/versions/0059_hierarchy_level_types.py) keys "group" to
# the Hebrew label "מדור" at rank 6, and "branch" to "ענף" at rank 5. Use the
# seeded keys here, not the labels (see COMMANDER_DELETE_MIN_LEVEL_KEY below
# for the same pattern already documented for a different action) — a
# Hebrew label passed to get_level_rank never matches any row and silently
# resolves to None, which dm_scope_covers_level treats as an unconditional
# denial regardless of the actor's actual level.
REQUEST_CANCELLATION_DUTY_MANAGER_MIN_LEVEL_KEY = "branch"

COMMANDER_EXEMPTION_MIN_LEVEL_KEY = "מדור"  # fallback default if no setting is configured
REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY = "מרכז"
RANGE_ATTENDANCE_EDIT_MIN_LEVEL_KEY = "ענף"  # fallback default if no setting is configured


def _commander_exemption_min_level(session: Session) -> str:
    try:
        value = get_setting(session, "exemptions.commander_exemption_min_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return COMMANDER_EXEMPTION_MIN_LEVEL_KEY


def dm_scope_covers_level(session: Session, *, scope_node: HierarchyNode, required_level_key: str) -> bool:
    """True iff scope_node's level rank is <= required_level_key's rank (i.e. scope_node
    is at that level or closer to root — lower rank number = closer to root)."""
    required_rank = get_level_rank(session, required_level_key)
    scope_rank = get_level_rank(session, scope_node.level)
    if required_rank is None or scope_rank is None:
        return False
    return scope_rank <= required_rank


def dm_scope_covers_target(
    session: Session,
    *,
    scope_root_ids: set[uuid.UUID],
    target_node: HierarchyNode | None,
    required_level_key: str,
) -> bool:
    """True iff target_node is covered by at least one of the given scope roots
    (i.e. one of the roots is an ancestor-or-self of target_node, per path_ids),
    AND that covering root's level is at or above required_level_key."""
    if target_node is None:
        return False
    for root_id in scope_root_ids:
        if root_id in target_node.path_ids:
            root_node = session.get(HierarchyNode, root_id)
            if root_node is not None and dm_scope_covers_level(
                session, scope_node=root_node, required_level_key=required_level_key
            ):
                return True
    return False


def _commanded_node_ids_only(session: Session, soldier_id: uuid.UUID) -> set[uuid.UUID]:
    from app.auth.authz import commanded_node_ids
    return commanded_node_ids(session, soldier_id)


def _dm_scope_node_ids_only(session: Session, soldier_id: uuid.UUID) -> set[uuid.UUID]:
    from app.auth.authz import dm_scope_node_ids
    return dm_scope_node_ids(session, soldier_id)


def rank_advancement_edit_authorized(
    session: Session, *, user: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """Whether ``user`` may correct a soldier's rank-advancement data.

    Administrators bypass the hierarchy check. Commanders derive scope only
    from nodes they command; duty managers derive it only from their explicit
    duty-manager scopes. In both cases the covering root must be at ``מדור``
    level or higher and contain the target node.
    """
    if user.role == "admin":
        return True
    if target_node is None:
        return False
    commander_root_ids = _commanded_node_ids_only(session, user.id)
    if dm_scope_covers_target(
        session, scope_root_ids=commander_root_ids, target_node=target_node, required_level_key="מדור",
    ):
        return True
    duty_manager_root_ids = _dm_scope_node_ids_only(session, user.id)
    return dm_scope_covers_target(
        session, scope_root_ids=duty_manager_root_ids, target_node=target_node, required_level_key="מדור",
    )


def request_cancellation_authorized(
    session: Session, *, user: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """Whether a senior commander/duty manager or admin may cancel a request."""
    if user.role == "admin":
        return True
    if target_node is None:
        return False
    if dm_scope_covers_target(
        session, scope_root_ids=_commanded_node_ids_only(session, user.id),
        target_node=target_node, required_level_key=REQUEST_CANCELLATION_COMMANDER_MIN_LEVEL_KEY,
    ):
        return True
    return dm_scope_covers_target(
        session, scope_root_ids=_dm_scope_node_ids_only(session, user.id),
        target_node=target_node, required_level_key=REQUEST_CANCELLATION_DUTY_MANAGER_MIN_LEVEL_KEY,
    )


def senior_commander_approval_authorized(
    session: Session, *, user: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """Whether a commander at מדור or above covers the target node."""
    if user.role == "admin":
        return True
    return target_node is not None and dm_scope_covers_target(
        session, scope_root_ids=_commanded_node_ids_only(session, user.id),
        target_node=target_node, required_level_key=REQUEST_CANCELLATION_COMMANDER_MIN_LEVEL_KEY,
    )


class RankAdvancementEditScope:
    """Precomputed per-request context for repeated
    ``rank_advancement_edit_authorized`` checks against many target nodes.

    ``rank_advancement_edit_authorized`` issues 2 uncached SELECTs (commander
    root ids, DM scope root ids) plus up to 2 more per candidate root via
    ``dm_scope_covers_target`` -> ``dm_scope_covers_level`` ->
    ``get_level_rank`` on every call. Callers that need to authorize many
    soldiers in one request (e.g. GET /soldiers) should build this once and
    call ``.authorized(target_node)`` per soldier instead, to avoid
    re-running the same actor-scoped queries once per soldier.
    """

    __slots__ = ("is_admin", "_covering_root_ids")

    def __init__(self, session: Session, *, user: Soldier) -> None:
        self.is_admin = user.role == "admin"
        self._covering_root_ids: set[uuid.UUID] = set()
        if self.is_admin:
            return
        commander_root_ids = _commanded_node_ids_only(session, user.id)
        duty_manager_root_ids = _dm_scope_node_ids_only(session, user.id)
        all_root_ids = commander_root_ids | duty_manager_root_ids
        if not all_root_ids:
            return
        mador_rank = get_level_rank(session, "מדור")
        if mador_rank is None:
            return
        rows = session.execute(
            select(HierarchyNode.id, HierarchyNode.level).where(HierarchyNode.id.in_(all_root_ids))
        ).all()
        level_keys = {level for _, level in rows}
        rank_by_level = {key: get_level_rank(session, key) for key in level_keys}
        self._covering_root_ids = {
            node_id
            for node_id, level in rows
            if (level_rank := rank_by_level.get(level)) is not None and level_rank <= mador_rank
        }

    def authorized(self, target_node: HierarchyNode | None) -> bool:
        if self.is_admin:
            return True
        if target_node is None or not self._covering_root_ids:
            return False
        return any(root_id in target_node.path_ids for root_id in self._covering_root_ids)


def _range_attendance_edit_min_level(session: Session) -> str:
    try:
        value = get_setting(session, "mitvachim.attendance_edit_min_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return RANGE_ATTENDANCE_EDIT_MIN_LEVEL_KEY


def range_attendance_edit_authorized(session: Session, *, user: Soldier, target_node: HierarchyNode) -> bool:
    """True iff `user` is a duty manager (not a commander) whose own DM-scope node
    is at `mitvachim.attendance_edit_min_level` rank or higher, and that scope
    covers target_node. Commanders never qualify, regardless of rank."""
    if user.role == "admin":
        return True
    dm_root_ids = _dm_scope_node_ids_only(session, user.id)
    required_level = _range_attendance_edit_min_level(session)
    return dm_scope_covers_target(
        session, scope_root_ids=dm_root_ids, target_node=target_node, required_level_key=required_level,
    )


def commander_can_grant_commander_exemption(
    session: Session, *, commander_id: uuid.UUID,
) -> bool:
    """True iff the soldier commands at least one node at level 'מדור' (or the
    configured exemptions.commander_exemption_min_level) or above (closer to root)."""
    mador_rank = get_level_rank(session, _commander_exemption_min_level(session))
    if mador_rank is None:
        return False
    commanded_nodes = _commanded_nodes(session, commander_id)
    for node in commanded_nodes:
        node_rank = get_level_rank(session, node.level)
        if node_rank is not None and node_rank <= mador_rank:
            return True
    return False


COMMANDER_ESCALATION_MIN_LEVEL_KEY = "department"  # fallback default if no setting is configured
# ^ get_level_rank matches HierarchyLevelType.key, not .label — the seed
# migration (alembic/versions/0059_hierarchy_level_types.py) keys "department"
# to the Hebrew label "מרכז" at rank 4. Use the seeded key here so this
# setting resolves out of the box on a fresh deployment, without requiring an
# admin to first customize hierarchy_level_types.


def _commander_escalation_min_level(session: Session) -> str:
    try:
        value = get_setting(session, "exemptions.commander_escalation_min_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return COMMANDER_ESCALATION_MIN_LEVEL_KEY


def duty_manager_exemption_immediate_apply_authorized(
    session: Session, *, user: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """True iff `user` is a duty manager whose DM-scope covers `target_node`
    at `exemptions.commander_escalation_min_level` (default מרכז) or above.
    Commanders never qualify here, regardless of rank or scope — only DMs
    (and, via the caller's separate admin bypass, admins) may apply a
    commander-exemption grant immediately without DM approval."""
    dm_root_ids = _dm_scope_node_ids_only(session, user.id)
    required_level = _commander_escalation_min_level(session)
    return dm_scope_covers_target(
        session, scope_root_ids=dm_root_ids, target_node=target_node,
        required_level_key=required_level,
    )


def has_any_exemption_immediate_apply_scope(session: Session, *, user: Soldier) -> bool:
    """Cheap `/me`-level flag mirroring has_any_commander_delete_scope: True
    iff `user` holds a DutyManagerScope at the configured minimum level or
    above, independent of any specific target soldier."""
    required_rank = get_level_rank(session, _commander_escalation_min_level(session))
    if required_rank is None:
        return False
    for node in _dm_scope_nodes(session, user.id):
        node_rank = get_level_rank(session, node.level)
        if node_rank is not None and node_rank <= required_rank:
            return True
    return False


COMMANDER_DELETE_MIN_LEVEL_KEY = "group"  # fallback default if no setting is configured
# ^ get_level_rank matches HierarchyLevelType.key, not .label — the seed
# migration (alembic/versions/0059_hierarchy_level_types.py) keys "group"
# to the Hebrew label "מדור" at rank 6. Use the seeded key here so this
# setting resolves out of the box on a fresh deployment, without requiring an
# admin to first customize hierarchy_level_types.


def _commander_delete_min_level(session: Session) -> str:
    try:
        value = get_setting(session, "soldiers.commander_delete_min_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return COMMANDER_DELETE_MIN_LEVEL_KEY


def commander_delete_soldier_authorized(
    session: Session, *, user: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """True iff `user` commands a node at `soldiers.commander_delete_min_level`
    (default מדור) or above (closer to root) whose subtree contains
    `target_node`."""
    commander_root_ids = _commanded_node_ids_only(session, user.id)
    required_level = _commander_delete_min_level(session)
    return dm_scope_covers_target(
        session, scope_root_ids=commander_root_ids, target_node=target_node,
        required_level_key=required_level,
    )


def has_any_commander_delete_scope(session: Session, *, user: Soldier) -> bool:
    """Cheap `/me`-level flag: True iff `user` commands ANY node at the
    configured minimum level or above — independent of any specific target
    soldier. Used only to decide whether to render the delete affordance at
    all; the actual delete call is still authorized per-target via
    `commander_delete_soldier_authorized`."""
    required_rank = get_level_rank(session, _commander_delete_min_level(session))
    if required_rank is None:
        return False
    commanded_nodes = _commanded_nodes(session, user.id)
    for node in commanded_nodes:
        node_rank = get_level_rank(session, node.level)
        if node_rank is not None and node_rank <= required_rank:
            return True
    return False


def _min_visible_level(session: Session) -> str:
    # Default is "מדור", NOT the fully-open "every_soldier" sentinel — a
    # missing/unset row must still block plain soldiers from seeing an
    # unrelated soldier's data, closing that leak without admin action.
    # "every_soldier" remains a valid value an admin can explicitly set later.
    try:
        value = get_setting(session, "transparency.min_visible_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return "מדור"


def _commanded_nodes(session: Session, soldier_id: uuid.UUID) -> list[HierarchyNode]:
    from app.auth.authz import commanded_node_ids
    ids = commanded_node_ids(session, soldier_id)
    if not ids:
        return []
    return list(
        session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(ids))).scalars().all()
    )


def _dm_scope_nodes(session: Session, soldier_id: uuid.UUID) -> list[HierarchyNode]:
    from app.auth.authz import dm_scope_node_ids
    ids = dm_scope_node_ids(session, soldier_id)
    if not ids:
        return []
    return list(
        session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(ids))).scalars().all()
    )


def _ancestor_n_up(session: Session, node: HierarchyNode, n: int) -> HierarchyNode:
    """Walk `n` steps toward the root along node.path_ids (root-first, self-last).
    Caps at the root if `n` exceeds the number of ancestors."""
    if n <= 0:
        return node
    target_idx = max(0, len(node.path_ids) - 1 - n)
    ancestor_id = node.path_ids[target_idx]
    if ancestor_id == node.id:
        return node
    ancestor = session.get(HierarchyNode, ancestor_id)
    return ancestor if ancestor is not None else node


def _best_commanded_rank(session: Session, soldier_id: uuid.UUID) -> int | None:
    """Most senior (lowest) rank among every node the soldier commands or
    duty-manages, or None if they hold neither role."""
    nodes = [*_commanded_nodes(session, soldier_id), *_dm_scope_nodes(session, soldier_id)]
    ranks = [get_level_rank(session, node.level) for node in nodes]
    ranks = [r for r in ranks if r is not None]
    return min(ranks) if ranks else None


def can_view_soldier_scope(
    session: Session, viewer: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """True iff `viewer` may see transparency/duty-history data belonging to a
    soldier assigned to `target_node`. Single source of truth for the
    transparency page, its fairness-components/effort-breakdown cards, and the
    other-soldier branch of GET /soldiers/{id}/duty-history."""
    if viewer.role == "admin":
        return True

    commander_expand = get_setting_int(session, "transparency.commander_levels_above", 0)
    for node in _commanded_nodes(session, viewer.id):
        ancestor = _ancestor_n_up(session, node, commander_expand)
        if target_node is not None and ancestor.id in target_node.path_ids:
            return True

    dm_expand = get_setting_int(session, "transparency.duty_manager_levels_above", 0)
    for node in _dm_scope_nodes(session, viewer.id):
        ancestor = _ancestor_n_up(session, node, dm_expand)
        if target_node is not None and ancestor.id in target_node.path_ids:
            return True

    threshold = _min_visible_level(session)
    if threshold == "every_soldier":
        return True

    threshold_rank = get_level_rank(session, threshold)
    if threshold_rank is None:
        return False
    best_rank = _best_commanded_rank(session, viewer.id)
    return best_rank is not None and best_rank <= threshold_rank


def has_any_visibility(session: Session, viewer: Soldier) -> bool:
    """Cheap endpoint-level gate: True iff `viewer` can see *something* under
    the transparency rule — used to 403 early instead of computing full row
    sets for someone who'd end up seeing nothing."""
    if viewer.role == "admin":
        return True
    if _commanded_nodes(session, viewer.id) or _dm_scope_nodes(session, viewer.id):
        return True
    return _min_visible_level(session) == "every_soldier"
