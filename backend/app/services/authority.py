# backend/app/services/authority.py
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode
from app.services.eligibility import RANKS_RASAN_AND_ABOVE
from app.services.hierarchy import get_level_rank

COMMANDER_EXEMPTION_MIN_LEVEL_KEY = "מדור"
REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY = "מרכז"


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


def commander_can_grant_commander_exemption(
    session: Session, *, commander_id: uuid.UUID, commander_rank: str | None,
) -> bool:
    """True iff commander_rank is רסן+, OR the soldier commands at least one node
    at level 'מדור' or above (closer to root)."""
    if commander_rank and commander_rank in RANKS_RASAN_AND_ABOVE:
        return True
    mador_rank = get_level_rank(session, COMMANDER_EXEMPTION_MIN_LEVEL_KEY)
    if mador_rank is None:
        return False
    commanded_nodes = session.execute(
        select(HierarchyNode).where(HierarchyNode.commander_id == commander_id)
    ).scalars().all()
    for node in commanded_nodes:
        node_rank = get_level_rank(session, node.level)
        if node_rank is not None and node_rank <= mador_rank:
            return True
    return False
