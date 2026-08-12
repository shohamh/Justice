from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import node_in_scope
from app.db.models import DutyType, HierarchyNode, RangeType, Soldier

_cache: dict[uuid.UUID, bool] = {}


def invalidate_alal_relevance_cache() -> None:
    """Call after any write that could change which nodes are אל"ל-relevant:
    DutyType create/update/delete. Mirrors the invalidate-on-write pattern used
    for the DutyAssignment.weapon_ineligible cache columns (duty_eligibility_watch.py)."""
    _cache.clear()


def _node_is_alal_relevant(session: Session, *, node: HierarchyNode) -> bool:
    alal_duty_types = session.execute(
        select(DutyType).where(
            DutyType.required_range_type == RangeType.alal, DutyType.active.is_(True),
        )
    ).scalars().all()
    return any(
        node_in_scope(duty_type.eligible_node_ids, node.path_ids) for duty_type in alal_duty_types
    )


def is_alal_relevant(session: Session, soldier: Soldier) -> bool:
    """True iff soldier's hierarchy node is structurally in scope for any active
    DutyType requiring required_range_type == alal. Cached per hierarchy_node_id
    (far fewer distinct nodes than soldiers); invalidated explicitly on DutyType
    writes rather than TTL'd, since duty-type config changes rarely."""
    if soldier.hierarchy_node_id is None:
        return False
    if soldier.hierarchy_node_id in _cache:
        return _cache[soldier.hierarchy_node_id]
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        _cache[soldier.hierarchy_node_id] = False
        return False
    result = _node_is_alal_relevant(session, node=node)
    _cache[soldier.hierarchy_node_id] = result
    return result
