from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import CommanderNotificationScope, Notification, NotificationPreference, NotificationType, Soldier
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


class CommanderScopeOut(BaseModel):
    id: uuid.UUID
    hierarchy_node_id: uuid.UUID


class AddScopeBody(BaseModel):
    hierarchy_node_id: uuid.UUID


class AnnounceBody(BaseModel):
    title: str
    body: str | None = None
    hierarchy_node_ids: list[uuid.UUID] | None = None


class PaginatedNotifications(BaseModel):
    items: list[NotificationOut]
    total: int


class UnreadCountOut(BaseModel):
    count: int


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
                                 in_app_enabled=p.in_app_enabled, push_enabled=p.push_enabled)
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
                                 in_app_enabled=p.in_app_enabled, push_enabled=p.push_enabled)
            for p in prefs]


@router.get("/notifications/commander-scopes", response_model=list[CommanderScopeOut])
def list_scopes(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[CommanderScopeOut]:
    if user.role not in ("commander", "duty_manager", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    scopes = svc.list_commander_scopes(session, commander_id=user.id)
    return [CommanderScopeOut(id=s.id, hierarchy_node_id=s.hierarchy_node_id) for s in scopes]


@router.post("/notifications/commander-scopes", response_model=CommanderScopeOut, status_code=201)
def add_scope(
    body: AddScopeBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CommanderScopeOut:
    if user.role not in ("commander", "duty_manager", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    scope = svc.add_commander_scope(session, commander_id=user.id,
                                     hierarchy_node_id=body.hierarchy_node_id)
    session.commit()
    return CommanderScopeOut(id=scope.id, hierarchy_node_id=scope.hierarchy_node_id)


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
