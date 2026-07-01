from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.authz import is_commander, is_duty_manager, scope_root_ids
from app.auth.deps import require_duty_manager_or_admin
from app.db.models import DutyManagerScope, DutyType, HierarchyNode, Soldier
from app.db.session import get_session
from app.routes.duty_config import DutyTypeOut, _dt_out
from app.routes.hierarchy import DutyManagerEntryOut, NodeOut, _out

router = APIRouter(prefix="/import-lookup", tags=["import-lookup"])


@router.get("/duty-types", response_model=list[DutyTypeOut])
def list_duty_types_for_import(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> list[DutyTypeOut]:
    return [_dt_out(d) for d in session.execute(select(DutyType)).scalars().all()]


@router.get("/hierarchy", response_model=list[NodeOut])
def list_hierarchy_for_import(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> list[NodeOut]:
    nodes = list(session.execute(select(HierarchyNode)).scalars().all())
    user_roots = scope_root_ids(session, user)
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)

    dm_by_node: dict = {n.id: [] for n in nodes}
    if nodes:
        dm_rows = session.execute(
            select(DutyManagerScope, Soldier.full_name)
            .join(Soldier, Soldier.id == DutyManagerScope.duty_manager_id)
            .where(DutyManagerScope.hierarchy_node_id.in_([n.id for n in nodes]))
        ).all()
        for entry, name in dm_rows:
            dm_by_node[entry.hierarchy_node_id].append(
                DutyManagerEntryOut(scope_id=entry.id, soldier_id=entry.duty_manager_id, name=name)
            )

    commander_ids = {n.commander_id for n in nodes if n.commander_id}
    commanders_by_id: dict = {}
    if commander_ids:
        commanders_by_id = {
            s.id: s for s in session.execute(
                select(Soldier).where(Soldier.id.in_(commander_ids))
            ).scalars().all()
        }

    return [
        _out(
            n, session, user=user,
            user_roots=user_roots,
            user_is_commander=user_is_commander,
            user_is_duty_manager=user_is_duty_manager,
            duty_managers=dm_by_node[n.id],
            commander=commanders_by_id.get(n.commander_id) if n.commander_id else None,
        )
        for n in nodes
    ]


class SoldierLookupOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    rank: str | None
    hierarchy_node_id: uuid.UUID | None
    hierarchy_node_name: str | None


@router.get("/soldiers", response_model=list[SoldierLookupOut])
def lookup_soldiers_for_import(
    personal_number: str | None = None,
    name: str | None = None,
    hierarchy_node_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> list[SoldierLookupOut]:
    if personal_number is None and name is None and hierarchy_node_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no_filter_provided")

    query = select(Soldier).where(Soldier.role == "soldier")
    if personal_number is not None:
        query = query.where(Soldier.personal_number == personal_number)
    if name is not None:
        query = query.where(Soldier.full_name.ilike(f"%{name}%"))
    if hierarchy_node_id is not None:
        descendant_ids = session.execute(
            select(HierarchyNode.id).where(
                or_(
                    HierarchyNode.id == hierarchy_node_id,
                    HierarchyNode.path_ids.any(hierarchy_node_id),
                )
            )
        ).scalars().all()
        query = query.where(Soldier.hierarchy_node_id.in_(descendant_ids))

    soldiers = list(session.execute(query).scalars().all())

    node_ids = {s.hierarchy_node_id for s in soldiers if s.hierarchy_node_id}
    nodes_by_id: dict[uuid.UUID, HierarchyNode] = {}
    if node_ids:
        nodes_by_id = {
            n.id: n for n in session.execute(
                select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
            ).scalars().all()
        }

    return [
        SoldierLookupOut(
            id=s.id,
            personal_number=s.personal_number,
            full_name=s.full_name,
            rank=s.rank,
            hierarchy_node_id=s.hierarchy_node_id,
            hierarchy_node_name=nodes_by_id[s.hierarchy_node_id].name if s.hierarchy_node_id in nodes_by_id else None,
        )
        for s in soldiers
    ]
