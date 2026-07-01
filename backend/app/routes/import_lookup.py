from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
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
