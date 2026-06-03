from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyManagerScope, HierarchyNode
from app.db.session import get_session
from app.services import dm_scope as svc

router = APIRouter(prefix="/duty-manager-scope", tags=["duty_manager_scope"])


class AssignRequest(BaseModel):
    soldier_id: uuid.UUID
    node_id: uuid.UUID


class ScopeEntryOut(BaseModel):
    id: uuid.UUID
    duty_manager_id: uuid.UUID
    hierarchy_node_id: uuid.UUID


@router.post("", response_model=ScopeEntryOut, status_code=status.HTTP_201_CREATED)
def assign_scope(
    body: AssignRequest,
    session: Session = Depends(get_session),
    user=Depends(require_password_changed),
) -> ScopeEntryOut:
    target_node = session.get(HierarchyNode, body.node_id)
    authorize(session, user, Action.DM_SCOPE_MANAGE, target_node=target_node)
    try:
        entry = svc.assign_dm_scope(
            session, soldier_id=body.soldier_id, node_id=body.node_id, actor_id=user.id
        )
        session.commit()
        return ScopeEntryOut(
            id=entry.id,
            duty_manager_id=entry.duty_manager_id,
            hierarchy_node_id=entry.hierarchy_node_id,
        )
    except svc.DmScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{entry_id}", status_code=status.HTTP_200_OK)
def remove_scope(
    entry_id: uuid.UUID,
    session: Session = Depends(get_session),
    user=Depends(require_password_changed),
) -> dict:
    entry = session.get(DutyManagerScope, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    target_node = session.get(HierarchyNode, entry.hierarchy_node_id)
    authorize(session, user, Action.DM_SCOPE_MANAGE, target_node=target_node)
    try:
        svc.remove_dm_scope(session, entry_id=entry_id, actor_id=user.id)
        session.commit()
        return {"status": "ok"}
    except svc.DmScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[ScopeEntryOut])
def list_scope(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user=Depends(require_password_changed),
) -> list[ScopeEntryOut]:
    if user.role != "admin" and user.id != soldier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    entries = (
        session.execute(
            select(DutyManagerScope).where(DutyManagerScope.duty_manager_id == soldier_id)
        )
        .scalars()
        .all()
    )
    return [
        ScopeEntryOut(
            id=e.id,
            duty_manager_id=e.duty_manager_id,
            hierarchy_node_id=e.hierarchy_node_id,
        )
        for e in entries
    ]
