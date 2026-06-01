from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    CommanderNotificationScope,
    HierarchyNode,
    Notification,
    NotificationPreference,
    NotificationType,
    Soldier,
    TelegramLink,
    TelegramOutbox,
)


class NotificationError(Exception):
    pass


def create_notification(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Notification:
    notif = Notification(
        soldier_id=soldier_id, type=type, title=title, body=body,
        reference_type=reference_type, reference_id=reference_id,
    )
    session.add(notif)
    session.flush()
    write_audit(session, actor_id=actor_id, action="notification.create",
                entity_type="notification", entity_id=notif.id,
                after={"soldier_id": str(soldier_id), "type": type.value, "title": title})
    cascade_to_commanders(session, type=type, title=title, body=body,
                          reference_type=reference_type, reference_id=reference_id,
                          actor_id=actor_id, original_soldier_id=soldier_id)
    _enqueue_push(session, soldier_id=soldier_id, text=title)
    return notif


def cascade_to_commanders(session: Session, *, type: NotificationType, title: str,
                          body: str | None, reference_type: str | None,
                          reference_id: uuid.UUID | None, actor_id: uuid.UUID | None,
                          original_soldier_id: uuid.UUID) -> None:
    soldier = session.get(Soldier, original_soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return
    soldier_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if soldier_node is None or not soldier_node.path_ids:
        return
    scopes = session.execute(
        select(CommanderNotificationScope).where(
            CommanderNotificationScope.hierarchy_node_id.in_(soldier_node.path_ids),
        )
    ).scalars().all()
    seen: set[uuid.UUID] = set()
    for scope in scopes:
        if scope.commander_id in seen:
            continue
        seen.add(scope.commander_id)
        _create_notif(session, soldier_id=scope.commander_id,
                      type=type, title=f"{soldier.full_name}: {title}",
                      body=body, reference_type=reference_type,
                      reference_id=reference_id, actor_id=actor_id)


def _create_notif(session: Session, *, soldier_id: uuid.UUID, type: NotificationType,
                  title: str, body: str | None, reference_type: str | None,
                  reference_id: uuid.UUID | None, actor_id: uuid.UUID | None) -> None:
    pref = session.execute(
        select(NotificationPreference).where(
            NotificationPreference.soldier_id == soldier_id,
            NotificationPreference.notification_type == type,
        )
    ).scalar_one_or_none()
    if pref is not None and not pref.in_app_enabled:
        return
    notif = Notification(soldier_id=soldier_id, type=type, title=title, body=body,
                         reference_type=reference_type, reference_id=reference_id)
    session.add(notif)
    _enqueue_push(session, soldier_id=soldier_id, text=title)


def _enqueue_push(session: Session, *, soldier_id: uuid.UUID, text: str) -> None:
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == soldier_id,
            TelegramLink.is_verified == True,
            TelegramLink.notifications_enabled == True,
            TelegramLink.telegram_chat_id.isnot(None),
        )
    ).scalar_one_or_none()
    if link is None:
        return
    session.add(TelegramOutbox(telegram_chat_id=link.telegram_chat_id, message_text=text))


def ensure_default_prefs(session: Session, *, soldier_id: uuid.UUID) -> None:
    existing = set(
        session.execute(
            select(NotificationPreference.notification_type).where(
                NotificationPreference.soldier_id == soldier_id,
            )
        ).scalars().all()
    )
    for nt in NotificationType:
        if nt not in existing:
            session.add(NotificationPreference(
                soldier_id=soldier_id, notification_type=nt,
                in_app_enabled=True, push_enabled=False,
            ))


def get_preferences(session: Session, *, soldier_id: uuid.UUID) -> list[NotificationPreference]:
    ensure_default_prefs(session, soldier_id=soldier_id)
    return list(session.execute(
        select(NotificationPreference).where(NotificationPreference.soldier_id == soldier_id)
        .order_by(NotificationPreference.notification_type)
    ).scalars().all())


def update_preferences(session: Session, *, soldier_id: uuid.UUID,
                       preferences: list[dict]) -> list[NotificationPreference]:
    ensure_default_prefs(session, soldier_id=soldier_id)
    for pd in preferences:
        pref = session.execute(
            select(NotificationPreference).where(
                NotificationPreference.soldier_id == soldier_id,
                NotificationPreference.notification_type == NotificationType(pd["notification_type"]),
            )
        ).scalar_one_or_none()
        if pref:
            pref.in_app_enabled = pd.get("in_app_enabled", pref.in_app_enabled)
            pref.push_enabled = pd.get("push_enabled", pref.push_enabled)
    return get_preferences(session, soldier_id=soldier_id)


def generate_code(session: Session, *, soldier_id: uuid.UUID) -> tuple[str, datetime]:
    code = secrets.token_hex(3).upper()[:6]
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    existing = session.execute(
        select(TelegramLink).where(TelegramLink.soldier_id == soldier_id)
    ).scalar_one_or_none()
    if existing:
        existing.verification_code = code
        existing.verification_expires_at = expires_at
        existing.is_verified = False
    else:
        session.add(TelegramLink(soldier_id=soldier_id, verification_code=code,
                                  verification_expires_at=expires_at))
    return code, expires_at


def telegram_status(session: Session, *, soldier_id: uuid.UUID) -> dict | None:
    link = session.execute(
        select(TelegramLink).where(TelegramLink.soldier_id == soldier_id)
    ).scalar_one_or_none()
    if link is None:
        return None
    return {"is_verified": link.is_verified, "telegram_username": link.telegram_username,
            "created_at": link.created_at.isoformat() if link.created_at else None,
            "verified_at": link.verified_at.isoformat() if link.verified_at else None}


def unlink_telegram(session: Session, *, soldier_id: uuid.UUID) -> None:
    link = session.execute(
        select(TelegramLink).where(TelegramLink.soldier_id == soldier_id)
    ).scalar_one_or_none()
    if link:
        link.telegram_chat_id = None
        link.telegram_username = None
        link.is_verified = False
        link.verified_at = None
        link.notifications_enabled = True


def list_notifications(session: Session, *, soldier_id: uuid.UUID,
                       is_read: bool | None = None, type: str | None = None,
                       offset: int = 0, limit: int = 20) -> tuple[list[Notification], int]:
    q = select(Notification).where(Notification.soldier_id == soldier_id)
    if is_read is not None:
        q = q.where(Notification.is_read == is_read)
    if type is not None:
        q = q.where(Notification.type == NotificationType(type))
    # Get total count first using a subquery or a separate count query
    count_q = select(Notification.id).where(Notification.soldier_id == soldier_id)
    if is_read is not None:
        count_q = count_q.where(Notification.is_read == is_read)
    if type is not None:
        count_q = count_q.where(Notification.type == NotificationType(type))
    total = len(session.execute(count_q).scalars().all())
    results = list(session.execute(q.order_by(Notification.created_at.desc()).offset(offset).limit(limit)).scalars().all())
    return results, total


def unread_count(session: Session, *, soldier_id: uuid.UUID) -> int:
    return len(session.execute(
        select(Notification.id).where(Notification.soldier_id == soldier_id, Notification.is_read == False)
    ).scalars().all())


def mark_read(session: Session, *, notification_id: uuid.UUID, soldier_id: uuid.UUID) -> Notification | None:
    n = session.execute(select(Notification).where(Notification.id == notification_id, Notification.soldier_id == soldier_id)).scalar_one_or_none()
    if n:
        n.is_read = True
    return n


def mark_all_read(session: Session, *, soldier_id: uuid.UUID) -> int:
    notifs = list(session.execute(select(Notification).where(Notification.soldier_id == soldier_id, Notification.is_read == False)).scalars().all())
    for n in notifs:
        n.is_read = True
    return len(notifs)


def delete_notification(session: Session, *, notification_id: uuid.UUID, soldier_id: uuid.UUID) -> bool:
    n = session.execute(select(Notification).where(Notification.id == notification_id, Notification.soldier_id == soldier_id)).scalar_one_or_none()
    if n:
        session.delete(n)
        return True
    return False


def list_commander_scopes(session: Session, *, commander_id: uuid.UUID) -> list[CommanderNotificationScope]:
    return list(session.execute(
        select(CommanderNotificationScope).where(CommanderNotificationScope.commander_id == commander_id)
    ).scalars().all())


def add_commander_scope(session: Session, *, commander_id: uuid.UUID, hierarchy_node_id: uuid.UUID) -> CommanderNotificationScope:
    s = CommanderNotificationScope(commander_id=commander_id, hierarchy_node_id=hierarchy_node_id)
    session.add(s)
    session.flush()
    return s


def remove_commander_scope(session: Session, *, scope_id: uuid.UUID, commander_id: uuid.UUID) -> bool:
    s = session.execute(select(CommanderNotificationScope).where(CommanderNotificationScope.id == scope_id, CommanderNotificationScope.commander_id == commander_id)).scalar_one_or_none()
    if s:
        session.delete(s)
        return True
    return False


def broadcast_announcement(session: Session, *, title: str, body: str | None = None,
                           hierarchy_node_ids: list[uuid.UUID] | None = None,
                           actor_id: uuid.UUID | None = None) -> int:
    if hierarchy_node_ids:
        nodes = session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(hierarchy_node_ids))).scalars().all()
        path_sets = [set(n.path_ids) for n in nodes if n.path_ids]
        if path_sets:
            combined_paths = set().union(*path_sets)
        else:
            combined_paths = set()
        soldiers = session.execute(
            select(Soldier).where(
                Soldier.hierarchy_node_id.in_(
                    select(HierarchyNode.id).where(
                        HierarchyNode.path_ids.overlap(list(combined_paths)) if combined_paths else select(HierarchyNode.id).where(False)
                    )
                )
            )
        ).scalars().all()
    else:
        soldiers = session.execute(select(Soldier)).scalars().all()
    count = 0
    for s in soldiers:
        create_notification(session, soldier_id=s.id, type=NotificationType.announcement, title=title, body=body, actor_id=actor_id)
        count += 1
    return count
