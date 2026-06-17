from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import CommanderNotificationScope, HierarchyNode, Notification, NotificationPreference, NotificationType, Soldier
from app.db.session import get_session
from app.services import notifications as svc
from app.settings import get_settings

router = APIRouter(tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    title: str
    body: str | None
    type: str
    reference_type: str | None
    reference_id: uuid.UUID | None
    is_read: bool
    created_at: datetime


class NotificationPrefOut(BaseModel):
    notification_type: str
    in_app_enabled: bool
    push_enabled: bool
    email_enabled: bool


class UpdatePrefsBody(BaseModel):
    preferences: list[dict]


class TelegramStatusOut(BaseModel):
    is_verified: bool
    telegram_username: str | None = None
    created_at: str | None = None
    verified_at: str | None = None


class GenerateCodeOut(BaseModel):
    code: str
    expires_at: datetime
    bot_username: str


class SoldierBrief(BaseModel):
    id: uuid.UUID
    full_name: str
    personal_number: str


class CommanderScopeOut(BaseModel):
    id: uuid.UUID
    hierarchy_node_id: uuid.UUID
    node_name: str | None
    depth: int
    soldiers: list[SoldierBrief]


class AddScopeBody(BaseModel):
    hierarchy_node_id: uuid.UUID
    depth: int = -1


class AnnounceBody(BaseModel):
    title: str
    body: str | None = None
    hierarchy_node_ids: list[uuid.UUID] | None = None


class PaginatedNotifications(BaseModel):
    items: list[NotificationOut]
    total: int


class UnreadCountOut(BaseModel):
    count: int


def _resolve_scope(session: Session, scope: CommanderNotificationScope) -> CommanderScopeOut:
    all_soldiers = session.execute(sa_select(Soldier)).scalars().all()

    # Batch-load all HierarchyNode rows needed in one query
    node_ids = {s.hierarchy_node_id for s in all_soldiers if s.hierarchy_node_id}
    node_ids.add(scope.hierarchy_node_id)
    node_map: dict[uuid.UUID, HierarchyNode] = {
        n.id: n for n in session.execute(
            sa_select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
        ).scalars()
    }

    scope_node = node_map.get(scope.hierarchy_node_id)
    node_name = scope_node.name if scope_node else None

    matched: list[SoldierBrief] = []
    for s in all_soldiers:
        if s.hierarchy_node_id is None:
            continue
        s_node = node_map.get(s.hierarchy_node_id)
        if s_node is None:
            continue
        path_ids = list(s_node.path_ids)
        if scope.hierarchy_node_id not in path_ids:
            continue
        if scope.depth >= 0:
            depth_from_scope = len(path_ids) - path_ids.index(scope.hierarchy_node_id) - 1
            if depth_from_scope > scope.depth:
                continue
        matched.append(SoldierBrief(id=s.id, full_name=s.full_name, personal_number=s.personal_number))

    return CommanderScopeOut(
        id=scope.id,
        hierarchy_node_id=scope.hierarchy_node_id,
        node_name=node_name,
        depth=scope.depth,
        soldiers=matched,
    )


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, soldier_id=n.soldier_id, title=n.title, body=n.body,
        type=n.type.value, reference_type=n.reference_type,
        reference_id=n.reference_id, is_read=n.is_read, created_at=n.created_at,
    )


def _err(msg: str, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


@router.get("/notifications", response_model=PaginatedNotifications)
def list_my_notifications(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
    is_read: bool | None = None,
    type: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> PaginatedNotifications:
    items, total = svc.list_notifications(session, soldier_id=user.id,
                                           is_read=is_read, type=type,
                                           offset=offset, limit=limit)
    return PaginatedNotifications(items=[_out(n) for n in items], total=total)


@router.get("/notifications/unread-count", response_model=UnreadCountOut)
def unread_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> UnreadCountOut:
    return UnreadCountOut(count=svc.unread_count(session, soldier_id=user.id))


@router.patch("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NotificationOut:
    n = svc.mark_read(session, notification_id=notification_id, soldier_id=user.id)
    if n is None:
        raise _err("not_found", 404)
    session.commit()
    return _out(n)


@router.patch("/notifications/read-all", response_model=UnreadCountOut)
def mark_all_read(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> UnreadCountOut:
    count = svc.mark_all_read(session, soldier_id=user.id)
    session.commit()
    return UnreadCountOut(count=count)


@router.delete("/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_notification(
    notification_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    if not svc.delete_notification(session, notification_id=notification_id, soldier_id=user.id):
        raise _err("not_found", 404)
    session.commit()


@router.get("/notifications/preferences", response_model=list[NotificationPrefOut])
def get_preferences(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NotificationPrefOut]:
    prefs = svc.get_preferences(session, soldier_id=user.id)
    return [NotificationPrefOut(notification_type=p.notification_type.value,
                                 in_app_enabled=p.in_app_enabled, push_enabled=p.push_enabled,
                                 email_enabled=p.email_enabled)
            for p in prefs]


@router.put("/notifications/preferences", response_model=list[NotificationPrefOut])
def update_preferences(
    body: UpdatePrefsBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NotificationPrefOut]:
    prefs = svc.update_preferences(session, soldier_id=user.id, preferences=body.preferences)
    session.commit()
    return [NotificationPrefOut(notification_type=p.notification_type.value,
                                 in_app_enabled=p.in_app_enabled, push_enabled=p.push_enabled,
                                 email_enabled=p.email_enabled)
            for p in prefs]


@router.get("/notifications/commander-scopes", response_model=list[CommanderScopeOut])
def list_scopes(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[CommanderScopeOut]:
    if user.role not in ("commander", "duty_manager", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    scopes = svc.list_commander_scopes(session, commander_id=user.id)
    return [_resolve_scope(session, s) for s in scopes]


@router.post("/notifications/commander-scopes", response_model=CommanderScopeOut, status_code=201)
def add_scope(
    body: AddScopeBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CommanderScopeOut:
    if user.role not in ("commander", "duty_manager", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    scope = svc.add_commander_scope(session, commander_id=user.id,
                                     hierarchy_node_id=body.hierarchy_node_id,
                                     depth=body.depth)
    session.flush()  # assign id without committing
    result = _resolve_scope(session, scope)
    session.commit()
    return result


@router.delete("/notifications/commander-scopes/{scope_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def remove_scope(
    scope_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    if user.role not in ("commander", "duty_manager", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    if not svc.remove_commander_scope(session, scope_id=scope_id, commander_id=user.id):
        raise _err("not_found", 404)
    session.commit()


@router.post("/notifications/announce", status_code=201)
def announce(
    body: AnnounceBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    count = svc.broadcast_announcement(session, title=body.title, body=body.body,
                                        hierarchy_node_ids=body.hierarchy_node_ids,
                                        actor_id=user.id)
    session.commit()
    return {"sent": count}


@router.post("/telegram/link", response_model=GenerateCodeOut)
def generate_code(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> GenerateCodeOut:
    code, expires_at = svc.generate_code(session, soldier_id=user.id)
    session.commit()
    return GenerateCodeOut(code=code, expires_at=expires_at, bot_username=get_settings().telegram_bot_username)


@router.get("/telegram/link/status", response_model=TelegramStatusOut)
def link_status(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TelegramStatusOut:
    status = svc.telegram_status(session, soldier_id=user.id)
    if status is None:
        return TelegramStatusOut(is_verified=False)
    return TelegramStatusOut(**status)


@router.delete("/telegram/link", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def unlink(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    svc.unlink_telegram(session, soldier_id=user.id)
    session.commit()


class ActionBody(BaseModel):
    token: str


@router.post("/action", status_code=200)
def redeem_action(
    body: ActionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    from app.services.action_tokens import redeem_token_from_link
    t = redeem_token_from_link(session, token=body.token, soldier_id=user.id)
    if t is None:
        raise HTTPException(status_code=404, detail="token_invalid")
    result = _dispatch_action(session, token=t, actor_id=user.id)
    session.commit()
    return result


def _dispatch_action(session: Session, *, token, actor_id: uuid.UUID) -> dict:
    """Dispatch an action token to the appropriate service function."""
    action = token.action
    resource_id = token.resource_id

    if action == "constraint:approve":
        from app.services import constraints as constraint_svc
        constraint_svc.approve_constraint(session, constraint_id=resource_id, actor_id=actor_id)
        return {"action": action, "status": "ok"}
    elif action == "constraint:reject":
        from app.services import constraints as constraint_svc
        constraint_svc.reject_constraint(session, constraint_id=resource_id, actor_id=actor_id, decision_note="")
        return {"action": action, "status": "ok"}
    elif action == "exemption:approve":
        from app.services import exemption_requests as exemption_svc
        exemption_svc.approve_request(session, request_id=resource_id, decided_by=actor_id)
        return {"action": action, "status": "ok"}
    elif action == "exemption:reject":
        from app.services import exemption_requests as exemption_svc
        exemption_svc.reject_request(session, request_id=resource_id, decided_by=actor_id, decision_note="")
        return {"action": action, "status": "ok"}
    elif action == "swap:approve_requester":
        from app.services import swaps as swap_svc
        swap_svc.approve_side(session, request_id=resource_id, side="requester", actor_id=actor_id)
        return {"action": action, "status": "ok"}
    elif action == "swap:approve_covering":
        from app.services import swaps as swap_svc
        swap_svc.claim_request(session, request_id=resource_id, covering_soldier_id=actor_id, actor_id=actor_id)
        return {"action": action, "status": "ok"}
    elif action == "swap:reject":
        from app.services import swaps as swap_svc
        swap_svc.reject_request(session, request_id=resource_id, decision_note="", actor_id=actor_id)
        return {"action": action, "status": "ok"}
    else:
        raise HTTPException(status_code=400, detail=f"unknown_action: {action}")
