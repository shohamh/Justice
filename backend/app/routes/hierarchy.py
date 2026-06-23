from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import uuid as _uuid_mod

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyLevelType, HierarchyNode, Soldier, SystemSetting
from app.db.session import get_session
from app.services import hierarchy as svc


def _get_root_node_id(session: Session) -> uuid.UUID | None:
    setting = session.get(SystemSetting, "system.root_node_id")
    return _uuid_mod.UUID(setting.value) if setting else None

router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])


class NodeOut(BaseModel):
    id: uuid.UUID
    level: str
    name: str
    parent_id: uuid.UUID | None
    commander_id: uuid.UUID | None
    commander_name: str | None = None
    path_ids: list[uuid.UUID]


class CreateNodeRequest(BaseModel):
    level: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None


class UpdateNodeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    commander_id: uuid.UUID | None = None
    level: str | None = Field(default=None, min_length=1, max_length=50)


class MoveNodeRequest(BaseModel):
    new_parent_id: uuid.UUID | None = None


class LevelTypeOut(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    rank: int


class CreateLevelTypeRequest(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=200)


class ReorderLevelTypesRequest(BaseModel):
    ordered_ids: list[uuid.UUID]


def _level_type_out(t: HierarchyLevelType) -> LevelTypeOut:
    return LevelTypeOut(id=t.id, key=t.key, label=t.label, rank=t.rank)


def _out(n: HierarchyNode, _session: Session | None = None) -> NodeOut:
    commander_name = None
    if n.commander_id and _session:
        cmdr = _session.get(Soldier, n.commander_id)
        if cmdr:
            commander_name = cmdr.full_name
    return NodeOut(
        id=n.id,
        level=n.level,
        name=n.name,
        parent_id=n.parent_id,
        commander_id=n.commander_id,
        commander_name=commander_name,
        path_ids=list(n.path_ids),
    )


@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
def create_node(
    body: CreateNodeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NodeOut:
    parent = session.get(HierarchyNode, body.parent_id) if body.parent_id else None
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=parent)
    try:
        node = svc.create_node(
            session, level=body.level, name=body.name, parent_id=body.parent_id, actor_id=user.id
        )
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node, session)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
def update_node(
    node_id: uuid.UUID,
    body: UpdateNodeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NodeOut:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    try:
        if body.name is not None:
            svc.rename_node(session, node_id=node_id, name=body.name, actor_id=user.id)
        if "commander_id" in body.model_fields_set:
            svc.set_commander(
                session, node_id=node_id, commander_id=body.commander_id, actor_id=user.id
            )
        if body.level is not None:
            svc.change_node_level(session, node_id=node_id, level=body.level, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node, session)


@router.post("/nodes/{node_id}/move", response_model=NodeOut)
def move_node(
    node_id: uuid.UUID,
    body: MoveNodeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NodeOut:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if node_id == _get_root_node_id(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="root_node_immovable")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    new_parent = session.get(HierarchyNode, body.new_parent_id) if body.new_parent_id else None
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=new_parent)
    try:
        svc.move_node(session, node_id=node_id, new_parent_id=body.new_parent_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node, session)


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_node(
    node_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if node_id == _get_root_node_id(session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="root_node_protected")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    try:
        svc.delete_node(session, node_id=node_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()


@router.get("/tree", response_model=list[NodeOut])
def get_tree(
    all: bool = False,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NodeOut]:
    root_node_id = _get_root_node_id(session)

    if all or user.role == "admin":
        nodes = list(session.execute(select(HierarchyNode)).scalars().all())
    elif user.role == "soldier":
        if user.hierarchy_node_id is None:
            return []
        node = session.get(HierarchyNode, user.hierarchy_node_id)
        nodes = [node] if node else []
    else:
        roots = scope_root_ids(session, user)
        if not roots:
            nodes = []
        else:
            nodes = [
                n
                for n in session.execute(select(HierarchyNode)).scalars().all()
                if any(r in n.path_ids for r in roots)
            ]

    # Always include the system root node so every role can use it as a calendar default.
    if root_node_id and not any(n.id == root_node_id for n in nodes):
        root_node = session.get(HierarchyNode, root_node_id)
        if root_node:
            nodes = [root_node, *nodes]

    return [_out(n, session) for n in nodes]


@router.get("/level-types", response_model=list[LevelTypeOut])
def list_level_types(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[LevelTypeOut]:
    types = session.execute(
        select(HierarchyLevelType).order_by(HierarchyLevelType.rank)
    ).scalars().all()
    return [_level_type_out(t) for t in types]


@router.post("/level-types", response_model=LevelTypeOut, status_code=status.HTTP_201_CREATED)
def create_level_type_route(
    body: CreateLevelTypeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> LevelTypeOut:
    authorize(session, user, Action.HIERARCHY_LEVEL_TYPE_MANAGE, target_node=None)
    try:
        level_type = svc.create_level_type(
            session, key=body.key, label=body.label, actor_id=user.id
        )
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(level_type)
    return _level_type_out(level_type)


@router.put("/level-types/reorder", response_model=list[LevelTypeOut])
def reorder_level_types_route(
    body: ReorderLevelTypesRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[LevelTypeOut]:
    authorize(session, user, Action.HIERARCHY_LEVEL_TYPE_MANAGE, target_node=None)
    try:
        types = svc.reorder_level_types(session, ordered_ids=body.ordered_ids, actor_id=user.id)
    except svc.ReorderViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "reorder_would_violate_tree", "violations": exc.violations},
        ) from exc
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return [_level_type_out(t) for t in types]


@router.delete("/level-types/{level_type_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_level_type_route(
    level_type_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    level_type = session.get(HierarchyLevelType, level_type_id)
    if level_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_LEVEL_TYPE_MANAGE, target_node=None)
    try:
        svc.delete_level_type(session, id=level_type_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
