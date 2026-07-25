from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.authz import is_commander, is_duty_manager, scope_root_ids
from app.db.models import HierarchyNode, Soldier


def _scoped_node_ids(session: Session, roots: set[uuid.UUID]) -> set[uuid.UUID]:
    """All hierarchy node ids that are `roots` themselves or descendants of one."""
    if not roots:
        return set()
    all_nodes = session.execute(select(HierarchyNode.id, HierarchyNode.path_ids)).all()
    return {
        node_id
        for node_id, path_ids in all_nodes
        if any(r in path_ids for r in roots)
    }


def search_soldiers(
    session: Session, *, user: Soldier, query: str, limit: int = 8
) -> list[dict]:
    q = query.strip()
    if not q:
        return []

    stmt = select(Soldier).where(
        Soldier.left_at.is_(None),
        or_(
            Soldier.full_name.ilike(f"%{q}%"),
            Soldier.personal_number.ilike(f"%{q}%"),
        ),
    )

    if user.role != "admin":
        roots = scope_root_ids(session, user)
        scoped_node_ids = _scoped_node_ids(session, roots)
        rows = session.execute(stmt).scalars().all()
        rows = [
            s for s in rows
            if s.id == user.id or (s.hierarchy_node_id in scoped_node_ids)
        ]
    else:
        rows = session.execute(stmt).scalars().all()

    rows = rows[:limit]
    return [
        {
            "id": str(s.id),
            "full_name": s.full_name,
            "personal_number": s.personal_number,
            "subtitle": s.rank,
        }
        for s in rows
    ]
