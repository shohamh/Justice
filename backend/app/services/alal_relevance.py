from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import node_in_scope
from app.db.models import DutyType, HierarchyNode, RangeType, Soldier


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
    DutyType requiring required_range_type == alal.

    Runs its query directly on every call rather than caching: caching this
    per-process was unsafe under the multi-worker prod deploy (each uvicorn
    worker has its own process memory, so invalidating the cache from one
    worker's write path left other workers serving a stale value indefinitely).
    The underlying query is two cheap lookups scoped to the soldier's single
    hierarchy node, and /me already performs several queries per request, so
    querying fresh here costs little.
    """
    if soldier.hierarchy_node_id is None:
        return False
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        return False
    return _node_is_alal_relevant(session, node=node)
