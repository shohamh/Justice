from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    CommanderNotificationDepth,
    CommanderNotificationScope,
    DutyManagerScope,
    EmailOutbox,
    HierarchyNode,
    Notification,
    NotificationPreference,
    NotificationType,
    Soldier,
    TelegramLink,
    TelegramOutbox,
)

# Depth filtering applies only to these types (others cascade without limit)
_DEPTH_FILTERED_TYPES = frozenset([
    NotificationType.constraint_pending,
    NotificationType.exemption_request_pending,
])

DEFAULT_PENDING_MAX_DEPTH = 2

_FRONTEND_PATHS: dict[str, str] = {
    "constraint_pending": "/constraints",
    "constraint_approved": "/constraints",
    "constraint_rejected": "/constraints",
    "exemption_request_pending": "/exemption-requests",
    "exemption_approved": "/exemption-requests",
    "exemption_rejected": "/exemption-requests",
    "swap_offer": "/swaps",
    "swap_offer_incoming": "/swaps",
    "swap_accepted": "/swaps",
    "swap_rejected": "/swaps",
    "assignment_created": "/schedule",
    "assignment_removed": "/schedule",
    "score_adjusted": "/profile",
    "announcement": "/notifications",
    "algorithm_job_done": "/algorithm",
    "algorithm_job_failed": "/algorithm",
    "enrollment_request_received": "/approvals",
    "enrollment_approved": "/profile",
    "enrollment_rejected": "/profile",
    "gimelim_dismissed": "/schedule",
    "gimelim_reserve_called_up": "/schedule",
    "gimelim_demoted_to_reserve": "/schedule",
    "gimelim_reassigned": "/schedule",
}


class NotificationError(Exception):
    pass


def _frontend_url(notification_type: NotificationType) -> str:
    from app.settings import get_settings
    base = get_settings().frontend_url.rstrip("/")
    path = _FRONTEND_PATHS.get(notification_type.value, "/notifications")
    return f"{base}{path}"


def _action_pair(notification_type: NotificationType) -> tuple[str, str] | None:
    """Return (approve_action, reject_action) for actionable types."""
    if notification_type == NotificationType.constraint_pending:
        return "constraint:approve", "constraint:reject"
    if notification_type == NotificationType.exemption_request_pending:
        return "exemption:approve", "exemption:reject"
    if notification_type == NotificationType.swap_offer:
        return "swap:approve_requester", "swap:reject"
    if notification_type == NotificationType.swap_offer_incoming:
        return "swap:approve_covering", "swap:reject"
    return None


def _commander_max_depth(
    session: Session, commander_id: uuid.UUID, notification_type: NotificationType
) -> int | None:
    row = session.execute(
        select(CommanderNotificationDepth).where(
            CommanderNotificationDepth.commander_id == commander_id,
            CommanderNotificationDepth.notification_type == notification_type,
        )
    ).scalar_one_or_none()
    if row is None:
        return DEFAULT_PENDING_MAX_DEPTH
    return row.max_depth  # None = unlimited


def _build_reply_markup(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    notification_type: NotificationType,
    reference_type: str | None,
    reference_id: uuid.UUID | None,
    soldier_gender: str | None,
) -> str:
    from app.services.action_tokens import (
        DEFAULT_ACTION_EXPIRY,
        DEFAULT_SILENCE_EXPIRY,
        create_token,
    )

    keyboard: list[list[dict]] = []

    pair = _action_pair(notification_type)
    if pair and reference_id:
        approve_action, reject_action = pair
        approve_tok = create_token(
            session, soldier_id=soldier_id, action=approve_action,
            resource_type=reference_type, resource_id=reference_id,
            expiry=DEFAULT_ACTION_EXPIRY,
        )
        reject_tok = create_token(
            session, soldier_id=soldier_id, action=reject_action,
            resource_type=reference_type, resource_id=reference_id,
            expiry=DEFAULT_ACTION_EXPIRY,
        )
        keyboard.append([
            {"text": "✅ אשר", "callback_data": approve_tok},
            {"text": "❌ דחה", "callback_data": reject_tok},
        ])

    silence_tok = create_token(
        session, soldier_id=soldier_id, action="silence:step1",
        extra_json={"notification_type": notification_type.value},
        expiry=DEFAULT_SILENCE_EXPIRY,
    )
    keyboard.append([{"text": "🔕 השתק", "callback_data": silence_tok}])

    open_label = "פתחי במערכת" if soldier_gender == "female" else "פתח במערכת"
    keyboard.append([{"text": f"🔗 {open_label}", "url": _frontend_url(notification_type)}])

    return json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False)


def _enqueue_push(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    text: str,
    notification_type: NotificationType | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    soldier_gender: str | None = None,
) -> None:
    from app.services.settings_loader import SettingNotFound, get_setting

    try:
        if not bool(get_setting(session, "telegram.enabled")):
            return
    except SettingNotFound:
        pass  # default: enabled

    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == soldier_id,
            TelegramLink.is_verified == True,  # noqa: E712
            TelegramLink.notifications_enabled == True,  # noqa: E712
            TelegramLink.telegram_chat_id.isnot(None),
        )
    ).scalar_one_or_none()
    if link is None:
        return

    reply_markup_json: str | None = None
    if notification_type is not None:
        reply_markup_json = _build_reply_markup(
            session,
            soldier_id=soldier_id,
            notification_type=notification_type,
            reference_type=reference_type,
            reference_id=reference_id,
            soldier_gender=soldier_gender,
        )

    session.add(TelegramOutbox(
        telegram_chat_id=link.telegram_chat_id,
        message_text=text,
        reply_markup_json=reply_markup_json,
    ))


def _enqueue_email(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    title: str,
    body: str | None = None,
    notification_type: NotificationType | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    soldier_gender: str | None = None,
) -> None:
    from app.services.email import render_notification_email
    from app.services.action_tokens import create_token, DEFAULT_ACTION_EXPIRY

    soldier = session.get(Soldier, soldier_id)
    if not soldier or not soldier.email or not soldier.email_verified:
        return

    pref = session.execute(
        select(NotificationPreference).where(
            NotificationPreference.soldier_id == soldier_id,
            NotificationPreference.notification_type == notification_type,
        )
    ).scalar_one_or_none() if notification_type else None
    if pref is not None and not pref.email_enabled:
        return

    approve_url: str | None = None
    reject_url: str | None = None
    if notification_type is not None:
        pair = _action_pair(notification_type)
        if pair and reference_id:
            from app.settings import get_settings
            approve_action, reject_action = pair
            approve_tok = create_token(
                session, soldier_id=soldier_id, action=approve_action,
                resource_type=reference_type, resource_id=reference_id,
                expiry=DEFAULT_ACTION_EXPIRY,
            )
            reject_tok = create_token(
                session, soldier_id=soldier_id, action=reject_action,
                resource_type=reference_type, resource_id=reference_id,
                expiry=DEFAULT_ACTION_EXPIRY,
            )
            base = get_settings().frontend_url.rstrip("/")
            approve_url = f"{base}/action?token={approve_tok}"
            reject_url = f"{base}/action?token={reject_tok}"

    app_url = _frontend_url(notification_type) if notification_type else ""
    html_body = render_notification_email(
        title=title,
        body=body,
        app_url=app_url,
        frontend_url=_get_frontend_base(),
        approve_url=approve_url,
        reject_url=reject_url,
        soldier_gender=soldier_gender,
    )
    session.add(EmailOutbox(
        to_address=soldier.email,
        subject=title,
        html_body=html_body,
    ))


def _get_frontend_base() -> str:
    from app.settings import get_settings
    return get_settings().frontend_url.rstrip("/")


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
) -> Notification | None:
    pref = session.execute(
        select(NotificationPreference).where(
            NotificationPreference.soldier_id == soldier_id,
            NotificationPreference.notification_type == type,
        )
    ).scalar_one_or_none()
    if pref is not None and not pref.in_app_enabled:
        return None
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
    soldier = session.get(Soldier, soldier_id)
    if pref is None or pref.push_enabled:
        _enqueue_push(
            session, soldier_id=soldier_id, text=title,
            notification_type=type,
            reference_type=reference_type,
            reference_id=reference_id,
            soldier_gender=soldier.gender if soldier else None,
        )
    _enqueue_email(
        session, soldier_id=soldier_id, title=title, body=body,
        notification_type=type,
        reference_type=reference_type,
        reference_id=reference_id,
        soldier_gender=soldier.gender if soldier else None,
    )
    return notif


def notify_commanders_of_request(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Send notification only to commanders in scope — not to the soldier themselves."""
    cascade_to_commanders(
        session, type=type, title=title, body=body,
        reference_type=reference_type, reference_id=reference_id,
        actor_id=actor_id, original_soldier_id=soldier_id,
    )


def notify_duty_managers_of_request(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Send notification only to duty managers whose scope covers the soldier's
    node at or above the regular-exemption approval level — not to commanders.

    Used for commander-escalated exemption requests, which start at
    pending_duty_manager and so skip the commander notification cascade."""
    from app.services.authority import REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY, dm_scope_covers_target

    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return
    target_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if target_node is None:
        return
    dm_ids = set(
        session.execute(select(DutyManagerScope.duty_manager_id)).scalars().all()
    )
    for dm_id in dm_ids:
        roots = set(
            session.execute(
                select(DutyManagerScope.hierarchy_node_id).where(
                    DutyManagerScope.duty_manager_id == dm_id
                )
            ).scalars().all()
        )
        if not dm_scope_covers_target(
            session, scope_root_ids=roots, target_node=target_node,
            required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
        ):
            continue
        _create_notif(
            session, soldier_id=dm_id, type=type,
            title=f"{soldier.full_name}: {title}", body=body,
            reference_type=reference_type, reference_id=reference_id,
            actor_id=actor_id,
        )


def cascade_to_commanders(
    session: Session, *, type: NotificationType, title: str,
    body: str | None, reference_type: str | None,
    reference_id: uuid.UUID | None, actor_id: uuid.UUID | None,
    original_soldier_id: uuid.UUID,
) -> None:
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
        # Depth filtering for pending approval types
        if type in _DEPTH_FILTERED_TYPES:
            max_depth = _commander_max_depth(session, scope.commander_id, type)
            if max_depth is not None:
                try:
                    scope_idx = soldier_node.path_ids.index(scope.hierarchy_node_id)
                except ValueError:
                    continue
                depth = len(soldier_node.path_ids) - 1 - scope_idx
                if depth > max_depth:
                    continue
        seen.add(scope.commander_id)
        _create_notif(
            session, soldier_id=scope.commander_id,
            type=type, title=f"{soldier.full_name}: {title}",
            body=body, reference_type=reference_type,
            reference_id=reference_id, actor_id=actor_id,
        )


def _create_notif(
    session: Session, *, soldier_id: uuid.UUID, type: NotificationType,
    title: str, body: str | None, reference_type: str | None,
    reference_id: uuid.UUID | None, actor_id: uuid.UUID | None,
) -> None:
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
    soldier = session.get(Soldier, soldier_id)
    if pref is None or pref.push_enabled:
        _enqueue_push(
            session, soldier_id=soldier_id, text=title,
            notification_type=type,
            reference_type=reference_type,
            reference_id=reference_id,
            soldier_gender=soldier.gender if soldier else None,
        )
    _enqueue_email(
        session, soldier_id=soldier_id, title=title, body=body,
        notification_type=type,
        reference_type=reference_type,
        reference_id=reference_id,
        soldier_gender=soldier.gender if soldier else None,
    )


def notify_enrollment_received(
    session: Session,
    *,
    soldier: Soldier,
    enrollment_req: "SoldierEnrollmentRequest",
    has_exemptions: bool,
) -> None:
    from app.db.models import DutyManagerScope, HierarchyLevelType, SoldierEnrollmentRequest
    from app.services.settings_loader import get_setting, SettingNotFound

    requested_node = session.get(HierarchyNode, enrollment_req.requested_node_id)
    if not requested_node or not requested_node.path_ids:
        return

    title = f"בקשת הצטרפות: {soldier.full_name}"

    # Notify commanders with scope over the requested node's path
    cmdr_scopes = session.execute(
        select(CommanderNotificationScope).where(
            CommanderNotificationScope.hierarchy_node_id.in_(requested_node.path_ids)
        )
    ).scalars().all()
    seen: set[uuid.UUID] = set()
    for scope in cmdr_scopes:
        if scope.commander_id in seen or scope.commander_id == soldier.id:
            continue
        seen.add(scope.commander_id)
        _create_notif(
            session, soldier_id=scope.commander_id,
            type=NotificationType.enrollment_request_received,
            title=title, body=None,
            reference_type="enrollment_request", reference_id=enrollment_req.id,
            actor_id=None,
        )

    if not has_exemptions:
        return

    # Notify eligible DMs (scope over path, level rank >= setting)
    try:
        min_rank = int(get_setting(session, "enrollment.min_dm_level_rank"))
    except (SettingNotFound, ValueError, TypeError):
        min_rank = 0

    dm_scopes = session.execute(
        select(DutyManagerScope).where(
            DutyManagerScope.hierarchy_node_id.in_(requested_node.path_ids)
        )
    ).scalars().all()
    for dm_scope in dm_scopes:
        if dm_scope.duty_manager_id in seen or dm_scope.duty_manager_id == soldier.id:
            continue
        scope_node = session.get(HierarchyNode, dm_scope.hierarchy_node_id)
        if not scope_node:
            continue
        lt = session.execute(
            select(HierarchyLevelType).where(HierarchyLevelType.key == scope_node.level)
        ).scalar_one_or_none()
        if lt is None or lt.rank < min_rank:
            continue
        seen.add(dm_scope.duty_manager_id)
        _create_notif(
            session, soldier_id=dm_scope.duty_manager_id,
            type=NotificationType.enrollment_request_received,
            title=title, body=None,
            reference_type="enrollment_request", reference_id=enrollment_req.id,
            actor_id=None,
        )


def notify_duty_managers_in_scope(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Notify every duty manager whose scope covers soldier_id's hierarchy node."""
    from app.db.models import DutyManagerScope

    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return
    soldier_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if soldier_node is None or not soldier_node.path_ids:
        return
    dm_scopes = session.execute(
        select(DutyManagerScope).where(
            DutyManagerScope.hierarchy_node_id.in_(soldier_node.path_ids)
        )
    ).scalars().all()
    seen: set[uuid.UUID] = set()
    for dm_scope in dm_scopes:
        if dm_scope.duty_manager_id in seen or dm_scope.duty_manager_id == soldier.id:
            continue
        seen.add(dm_scope.duty_manager_id)
        _create_notif(
            session, soldier_id=dm_scope.duty_manager_id,
            type=type, title=f"{soldier.full_name}: {title}",
            body=body, reference_type=reference_type,
            reference_id=reference_id, actor_id=actor_id,
        )


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
                in_app_enabled=True, push_enabled=False, email_enabled=True,
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
            pref.email_enabled = pd.get("email_enabled", pref.email_enabled)
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
        select(Notification.id).where(Notification.soldier_id == soldier_id, Notification.is_read == False)  # noqa: E712
    ).scalars().all())


def mark_read(session: Session, *, notification_id: uuid.UUID, soldier_id: uuid.UUID) -> Notification | None:
    n = session.execute(select(Notification).where(Notification.id == notification_id, Notification.soldier_id == soldier_id)).scalar_one_or_none()
    if n:
        n.is_read = True
    return n


def mark_all_read(session: Session, *, soldier_id: uuid.UUID) -> int:
    notifs = list(session.execute(select(Notification).where(Notification.soldier_id == soldier_id, Notification.is_read == False)).scalars().all())  # noqa: E712
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


def add_commander_scope(session: Session, *, commander_id: uuid.UUID, hierarchy_node_id: uuid.UUID, depth: int = -1) -> CommanderNotificationScope:
    s = CommanderNotificationScope(commander_id=commander_id, hierarchy_node_id=hierarchy_node_id, depth=depth)
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
        nodes = session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(hierarchy_node_ids))
        ).scalars().all()
        path_sets = [set(n.path_ids) for n in nodes if n.path_ids]
        if path_sets:
            combined_paths = set().union(*path_sets)
            soldiers = session.execute(
                select(Soldier).where(
                    Soldier.hierarchy_node_id.in_(
                        select(HierarchyNode.id).where(
                            HierarchyNode.path_ids.overlap(list(combined_paths))
                        )
                    )
                )
            ).scalars().all()
        else:
            soldiers = []
    else:
        soldiers = session.execute(select(Soldier)).scalars().all()
    count = 0
    for s in soldiers:
        create_notification(session, soldier_id=s.id, type=NotificationType.announcement,
                            title=title, body=body, actor_id=actor_id)
        count += 1
    return count
