from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.authz import scope_root_ids
from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, HierarchyNode, Soldier


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


def search_duties(
    session: Session, *, user: Soldier, query: str, limit: int = 8
) -> list[dict]:
    q = query.strip()
    if not q:
        return []

    stmt = (
        select(DutyShift, DutyType, DutyLocation)
        .join(DutyType, DutyShift.duty_type_id == DutyType.id)
        .join(DutyLocation, DutyShift.duty_location_id == DutyLocation.id)
        .where(
            or_(
                DutyType.name.ilike(f"%{q}%"),
                DutyType.description.ilike(f"%{q}%"),
            )
        )
    )
    rows = session.execute(stmt).all()

    if user.role != "admin":
        roots = scope_root_ids(session, user)
        scoped_node_ids = _scoped_node_ids(session, roots)
        assigned_soldier_ids = {
            sid
            for (sid,) in session.execute(
                select(DutyAssignment.soldier_id).where(
                    DutyAssignment.duty_shift_id.in_([shift.id for shift, _, _ in rows])
                )
            ).all()
        }
        in_scope_soldier_ids = {
            s.id
            for s in session.execute(
                select(Soldier).where(Soldier.id.in_(assigned_soldier_ids))
            ).scalars().all()
            if s.id == user.id or s.hierarchy_node_id in scoped_node_ids
        }
        visible_shift_ids = {
            sid
            for (sid,) in session.execute(
                select(DutyAssignment.duty_shift_id).where(
                    DutyAssignment.soldier_id.in_(in_scope_soldier_ids)
                )
            ).all()
        }
        rows = [r for r in rows if r[0].id in visible_shift_ids]

    rows = rows[:limit]
    return [
        {
            "id": str(shift.id),
            "duty_type_name": duty_type.name,
            "start_date": shift.start_date.isoformat(),
            "end_date": shift.end_date.isoformat(),
            "location_name": location.name,
        }
        for shift, duty_type, location in rows
    ]
