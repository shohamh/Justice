from __future__ import annotations

import hashlib
import json
import uuid
import uuid as _uuid_mod
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, aliased

from app.auth.authz import Action, authorize, can, is_commander, is_duty_manager, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import (
    DutyManagerScope,
    HierarchyLevelType,
    HierarchyNode,
    Soldier,
    SystemSetting,
)
from app.db.session import get_session
from app.services import hierarchy as svc
from app.settings import get_settings


def _get_root_node_id(session: Session) -> uuid.UUID | None:
    setting = session.get(SystemSetting, "system.root_node_id")
    return _uuid_mod.UUID(setting.value) if setting else None

router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])


class DutyManagerEntryOut(BaseModel):
    scope_id: uuid.UUID
    soldier_id: uuid.UUID
    name: str


class NodeOut(BaseModel):
    id: uuid.UUID
    level: str
    name: str
    parent_id: uuid.UUID | None
    commander_id: uuid.UUID | None
    commander_name: str | None = None
    path_ids: list[uuid.UUID]
    duty_managers: list[DutyManagerEntryOut] = []
    dm_manageable: bool = False
    can_edit: bool = False
    has_children: bool = False
    has_soldiers: bool = False


class HierarchyNodeSummaryOut(BaseModel):
    id: uuid.UUID
    level: str
    name: str


class MyCommandScopeOut(BaseModel):
    commanded_nodes: list[HierarchyNodeSummaryOut]
    assigned_node: HierarchyNodeSummaryOut | None


class NodeBranchPageOut(BaseModel):
    items: list[NodeOut]
    next_cursor: str | None
    has_more: bool


class NodeSearchMatchOut(BaseModel):
    node: NodeOut
    path: list[NodeOut]


class NodeSearchOut(BaseModel):
    matches: list[NodeSearchMatchOut]
    has_more: bool


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


def _out(
    n: HierarchyNode,
    session: Session,
    *,
    user: Soldier,
    user_roots: set[uuid.UUID],
    user_is_commander: bool,
    user_is_duty_manager: bool,
    duty_managers: list[DutyManagerEntryOut] | None = None,
    commander: Soldier | None = None,
    has_children: bool = False,
    has_soldiers: bool = False,
) -> NodeOut:
    commander_name = None
    if n.commander_id:
        cmdr = commander if commander is not None else session.get(Soldier, n.commander_id)
        if cmdr:
            commander_name = cmdr.full_name

    if duty_managers is None:
        dm_rows = session.execute(
            select(DutyManagerScope, Soldier.full_name)
            .join(Soldier, Soldier.id == DutyManagerScope.duty_manager_id)
            .where(DutyManagerScope.hierarchy_node_id == n.id)
        ).all()
        duty_managers = [
            DutyManagerEntryOut(scope_id=entry.id, soldier_id=entry.duty_manager_id, name=name)
            for entry, name in dm_rows
        ]

    dm_manageable = can(
        user,
        Action.DM_SCOPE_MANAGE,
        target_node=n,
        roots=user_roots,
        is_commander=user_is_commander,
        is_duty_manager=user_is_duty_manager,
    )

    # I-1: derive can_edit directly from the same can()/HIERARCHY_MANAGE check
    # the mutation endpoints enforce (authorize(..., Action.HIERARCHY_MANAGE, ...))
    # instead of an ad-hoc boolean, so the displayed flag can never drift from
    # what the buttons it gates actually do server-side.
    can_edit = can(
        user,
        Action.HIERARCHY_MANAGE,
        target_node=n,
        roots=user_roots,
        is_commander=user_is_commander,
        is_duty_manager=user_is_duty_manager,
    )

    return NodeOut(
        id=n.id,
        level=n.level,
        name=n.name,
        parent_id=n.parent_id,
        commander_id=n.commander_id,
        commander_name=commander_name,
        path_ids=list(n.path_ids),
        duty_managers=duty_managers,
        dm_manageable=dm_manageable,
        can_edit=can_edit,
        has_children=has_children,
        has_soldiers=has_soldiers,
    )


def _tree_revision(session: Session) -> int:
    # The roster revision has statement-level invalidation triggers for hierarchy
    # node changes. Reuse it so a child cursor cannot cross a hierarchy mutation.
    return session.execute(
        sql_text("SELECT revision FROM soldier_roster_revision WHERE singleton = TRUE")
    ).scalar_one()


def _tree_cursor_binding(
    session: Session,
    *,
    user: Soldier,
    parent: HierarchyNode | None,
) -> str:
    roots = scope_root_ids(session, user)
    payload = {
        "actor_id": str(user.id),
        "actor_role": user.role,
        "actor_node_id": str(user.hierarchy_node_id) if user.hierarchy_node_id else None,
        "scope_roots": sorted(str(root) for root in roots),
        "is_commander": is_commander(session, user.id),
        "is_duty_manager": is_duty_manager(session, user.id),
        "parent_id": str(parent.id) if parent else None,
        "parent_path": [str(part) for part in parent.path_ids] if parent else None,
        "page_size": 100,
        "order": "lower_name_uuid_asc",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _decode_tree_cursor(cursor: str, binding: str, revision: int) -> tuple[str, uuid.UUID]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            cursor, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        if (
            payload.get("purpose") != "hierarchy_branch"
            or payload.get("version") != 1
            or payload.get("binding") != binding
            or not isinstance(payload.get("key"), str)
            or not isinstance(payload.get("id"), str)
            or type(payload.get("revision")) is not int
        ):
            raise ValueError("cursor_mismatch")
        if payload["revision"] != revision:
            raise HTTPException(status_code=409, detail="stale_cursor")
        return payload["key"], uuid.UUID(payload["id"])
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="invalid_cursor") from exc


def _out_many(
    nodes: list[HierarchyNode],
    session: Session,
    *,
    user: Soldier,
    child_ids: set[uuid.UUID],
    soldier_node_ids: set[uuid.UUID],
) -> list[NodeOut]:
    if not nodes:
        return []
    user_roots = scope_root_ids(session, user)
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)
    node_ids = [node.id for node in nodes]
    dm_by_node: dict[uuid.UUID, list[DutyManagerEntryOut]] = {node_id: [] for node_id in node_ids}
    dm_rows = session.execute(
        select(DutyManagerScope, Soldier.full_name)
        .join(Soldier, Soldier.id == DutyManagerScope.duty_manager_id)
        .where(DutyManagerScope.hierarchy_node_id.in_(node_ids))
    ).all()
    for entry, name in dm_rows:
        dm_by_node[entry.hierarchy_node_id].append(
            DutyManagerEntryOut(scope_id=entry.id, soldier_id=entry.duty_manager_id, name=name)
        )

    commander_ids = {node.commander_id for node in nodes if node.commander_id}
    commanders_by_id = (
        {
            commander.id: commander
            for commander in session.execute(
                select(Soldier).where(Soldier.id.in_(commander_ids))
            ).scalars().all()
        }
        if commander_ids
        else {}
    )
    return [
        _out(
            node,
            session,
            user=user,
            user_roots=user_roots,
            user_is_commander=user_is_commander,
            user_is_duty_manager=user_is_duty_manager,
            duty_managers=dm_by_node[node.id],
            commander=commanders_by_id.get(node.commander_id) if node.commander_id else None,
            has_children=node.id in child_ids,
            has_soldiers=node.id in soldier_node_ids,
        )
        for node in nodes
    ]


def _node_presence(session: Session, nodes: list[HierarchyNode]) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    if not nodes:
        return set(), set()
    node_ids = [node.id for node in nodes]
    child_ids = set(
        session.execute(
            select(HierarchyNode.parent_id)
            .where(HierarchyNode.parent_id.in_(node_ids))
            .distinct()
        ).scalars()
    )
    soldier_node_ids = set(
        session.execute(
            select(Soldier.hierarchy_node_id)
            .where(Soldier.hierarchy_node_id.in_(node_ids))
            .distinct()
        ).scalars()
    )
    return child_ids, soldier_node_ids


@router.get("/branches", response_model=NodeBranchPageOut)
def get_hierarchy_branch_page(
    parent_id: uuid.UUID | None = None,
    cursor: str | None = Query(default=None, max_length=4096),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NodeBranchPageOut:
    """Read one bounded, stable page of roots or direct children."""
    parent = session.get(HierarchyNode, parent_id) if parent_id else None
    if parent_id and parent is None:
        raise HTTPException(status_code=404, detail="not_found")
    binding = _tree_cursor_binding(session, user=user, parent=parent)
    revision = _tree_revision(session)
    last_key, last_id = _decode_tree_cursor(cursor, binding, revision) if cursor else (None, None)

    child = aliased(HierarchyNode)
    has_children = exists(
        select(child.id).where(child.parent_id == HierarchyNode.id)
    ).label("has_children")
    has_soldiers = exists(
        select(Soldier.id).where(Soldier.hierarchy_node_id == HierarchyNode.id)
    ).label("has_soldiers")
    sort_key = func.lower(HierarchyNode.name)
    statement = select(HierarchyNode, sort_key.label("sort_key"), has_children, has_soldiers)
    statement = statement.where(
        HierarchyNode.parent_id == parent_id
        if parent_id is not None
        else HierarchyNode.parent_id.is_(None)
    )
    if last_key is not None and last_id is not None:
        statement = statement.where(
            or_(sort_key > last_key, and_(sort_key == last_key, HierarchyNode.id > last_id))
        )
    rows = session.execute(
        statement.order_by(sort_key.asc(), HierarchyNode.id.asc()).limit(101)
    ).all()
    has_more = len(rows) > 100
    rows = rows[:100]
    nodes = [row[0] for row in rows]
    child_ids = {row[0].id for row in rows if row[2]}
    soldier_node_ids = {row[0].id for row in rows if row[3]}
    items = _out_many(
        nodes,
        session,
        user=user,
        child_ids=child_ids,
        soldier_node_ids=soldier_node_ids,
    )
    if _tree_revision(session) != revision:
        raise HTTPException(status_code=409, detail="stale_cursor")
    next_cursor = None
    if has_more:
        settings = get_settings()
        last = rows[-1]
        next_cursor = jwt.encode(
            {
                "purpose": "hierarchy_branch",
                "version": 1,
                "binding": binding,
                "key": last.sort_key,
                "id": str(last[0].id),
                "revision": revision,
                "exp": datetime.now(UTC) + timedelta(hours=24),
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
    return NodeBranchPageOut(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/search", response_model=NodeSearchOut)
def search_hierarchy_nodes(
    q: str = Query(default="", max_length=200),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NodeSearchOut:
    """Return a small authorized search result set with each match's full path."""
    normalized = q.strip()
    if not normalized:
        return NodeSearchOut(matches=[], has_more=False)
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    sort_key = func.lower(HierarchyNode.name)
    rows = session.execute(
        select(HierarchyNode)
        .where(HierarchyNode.name.ilike(pattern, escape="\\"))
        .order_by(sort_key.asc(), HierarchyNode.id.asc())
        .limit(21)
    ).scalars().all()
    has_more = len(rows) > 20
    matches = rows[:20]
    path_ids = {node_id for node in matches for node_id in (node.path_ids or [node.id])}
    path_nodes = (
        list(session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(path_ids))).scalars())
        if path_ids
        else []
    )
    child_ids, soldier_node_ids = _node_presence(session, path_nodes)
    enriched = _out_many(
        path_nodes,
        session,
        user=user,
        child_ids=child_ids,
        soldier_node_ids=soldier_node_ids,
    )
    by_id = {node.id: node for node in enriched}
    results = [
        NodeSearchMatchOut(
            node=by_id[match.id],
            path=[by_id[node_id] for node_id in (match.path_ids or [match.id]) if node_id in by_id],
        )
        for match in matches
        if match.id in by_id
    ]
    return NodeSearchOut(matches=results, has_more=has_more)


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
    return _out(
        node, session, user=user,
        user_roots=scope_root_ids(session, user),
        user_is_commander=is_commander(session, user.id),
        user_is_duty_manager=is_duty_manager(session, user.id),
    )


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
    return _out(
        node, session, user=user,
        user_roots=scope_root_ids(session, user),
        user_is_commander=is_commander(session, user.id),
        user_is_duty_manager=is_duty_manager(session, user.id),
    )


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
    return _out(
        node, session, user=user,
        user_roots=scope_root_ids(session, user),
        user_is_commander=is_commander(session, user.id),
        user_is_duty_manager=is_duty_manager(session, user.id),
    )


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

    # The tree is always returned in full regardless of caller role — this endpoint is a
    # display convenience, not an access-control boundary. Every mutating hierarchy
    # endpoint (create/update/move/delete) enforces its own scope check via authorize()/
    # can() against the specific target_node, independent of what this GET returns. The
    # `all` query param is now a no-op kept for backward compatibility with existing callers.
    nodes = list(session.execute(select(HierarchyNode)).scalars().all())

    # Always include the system root node so every role can use it as a calendar default.
    if root_node_id and not any(n.id == root_node_id for n in nodes):
        root_node = session.get(HierarchyNode, root_node_id)
        if root_node:
            nodes = [root_node, *nodes]

    child_ids, soldier_node_ids = _node_presence(session, nodes)
    return _out_many(
        nodes,
        session,
        user=user,
        child_ids=child_ids,
        soldier_node_ids=soldier_node_ids,
    )


@router.get("/my-command-scope", response_model=MyCommandScopeOut)
def get_my_command_scope(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> MyCommandScopeOut:
    scope_rows = session.execute(
        select(
            HierarchyNode.id,
            HierarchyNode.level,
            HierarchyNode.name,
            HierarchyNode.commander_id,
        ).where(
            or_(
                HierarchyNode.commander_id == user.id,
                HierarchyNode.id == user.hierarchy_node_id,
            )
        )
    ).all()
    commanded_nodes: list[HierarchyNodeSummaryOut] = []
    assigned_node = None
    for row in scope_rows:
        summary = HierarchyNodeSummaryOut(id=row.id, level=row.level, name=row.name)
        if row.commander_id == user.id:
            commanded_nodes.append(summary)
        if row.id == user.hierarchy_node_id:
            assigned_node = summary

    return MyCommandScopeOut(
        commanded_nodes=commanded_nodes,
        assigned_node=assigned_node,
    )


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
