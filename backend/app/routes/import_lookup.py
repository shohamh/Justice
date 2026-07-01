from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin
from app.db.models import DutyType, HierarchyNode, Soldier
from app.db.session import get_session
from app.routes.duty_config import DutyTypeOut, _dt_out
from app.routes.hierarchy import NodeOut, _out
from app.auth.authz import is_commander, is_duty_manager, scope_root_ids

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
    return [
        _out(
            n, session, user=user,
            user_roots=user_roots,
            user_is_commander=user_is_commander,
            user_is_duty_manager=user_is_duty_manager,
        )
        for n in nodes
    ]
