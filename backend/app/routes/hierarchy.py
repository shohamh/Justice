from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import hierarchy as svc

router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])


class NodeOut(BaseModel):
    id: uuid.UUID
    level: str
    name: str
    parent_id: uuid.UUID | None
    commander_id: uuid.UUID | None
    path_ids: list[uuid.UUID]


class CreateNodeRequest(BaseModel):
    level: str = Field(pattern="^(department|branch|group|team)$")
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None


class UpdateNodeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    commander_id: uuid.UUID | None = None


class MoveNodeRequest(BaseModel):
    new_parent_id: uuid.UUID | None = None


def _out(n: HierarchyNode) -> NodeOut:
    return NodeOut(id=n.id, level=n.level, name=n.name, parent_id=n.parent_id,
                   commander_id=n.commander_id, path_ids=list(n.path_ids))


@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
def create_node(body: CreateNodeRequest, session: Session = Depends(get_session),
                user: Soldier = Depends(require_password_changed)) -> NodeOut:
    parent = session.get(HierarchyNode, body.parent_id) if body.parent_id else None
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=parent)
    try:
        node = svc.create_node(session, level=body.level, name=body.name,
                               parent_id=body.parent_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
def update_node(node_id: uuid.UUID, body: UpdateNodeRequest, session: Session = Depends(get_session),
                user: Soldier = Depends(require_password_changed)) -> NodeOut:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    try:
        if body.name is not None:
            svc.rename_node(session, node_id=node_id, name=body.name, actor_id=user.id)
        if "commander_id" in body.model_fields_set:
            svc.set_commander(session, node_id=node_id, commander_id=body.commander_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node)


@router.post("/nodes/{node_id}/move", response_model=NodeOut)
def move_node(node_id: uuid.UUID, body: MoveNodeRequest, session: Session = Depends(get_session),
              user: Soldier = Depends(require_password_changed)) -> NodeOut:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    new_parent = session.get(HierarchyNode, body.new_parent_id) if body.new_parent_id else None
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=new_parent)
    try:
        svc.move_node(session, node_id=node_id, new_parent_id=body.new_parent_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node)


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(node_id: uuid.UUID, session: Session = Depends(get_session),
                user: Soldier = Depends(require_password_changed)) -> None:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    try:
        svc.delete_node(session, node_id=node_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()


@router.get("/tree", response_model=list[NodeOut])
def get_tree(session: Session = Depends(get_session),
             user: Soldier = Depends(require_password_changed)) -> list[NodeOut]:
    if user.role == "admin":
        nodes = session.execute(select(HierarchyNode)).scalars().all()
    else:
        roots = scope_root_ids(session, user)
        if not roots:
            return []
        nodes = [
            n for n in session.execute(select(HierarchyNode)).scalars().all()
            if any(r in n.path_ids for r in roots)
        ]
    return [_out(n) for n in nodes]
