from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import (
    CommanderNotificationDepth,
    NotificationPreference,
    NotificationType,
    TelegramActionToken,
)
from app.services import constraints as constraint_svc
from app.services import exemption_requests as exemption_svc
from app.services import swaps as swap_svc
from app.services.action_tokens import DEFAULT_SILENCE_EXPIRY, create_token

_DEPTH_TYPES = frozenset([
    NotificationType.constraint_pending,
    NotificationType.exemption_request_pending,
])

_TYPE_LABELS: dict[str, str] = {
    "constraint_pending": "בקשות אילוץ",
    "exemption_request_pending": "בקשות פטור",
    "swap_offer": "הצעות החלפה",
    "swap_offer_incoming": "בקשות החלפה נכנסות",
    "assignment_created": "שיבוצים חדשים",
    "assignment_removed": "שיבוצים שבוטלו",
    "announcement": "הכרזות",
    "score_adjusted": "עדכוני ניקוד",
    "swap_accepted": "אישורי החלפה",
    "swap_rejected": "דחיות החלפה",
    "constraint_approved": "אישורי אילוץ",
    "constraint_rejected": "דחיות אילוץ",
    "exemption_approved": "אישורי פטור",
    "exemption_rejected": "דחיות פטור",
    "algorithm_job_done": "עבודות אלגוריתם",
    "algorithm_job_failed": "כשלי אלגוריתם",
}


def execute_action(token_row: TelegramActionToken, session: Session) -> str:
    """Execute an approve/claim action (no reason required). Returns Hebrew response text."""
    action = token_row.action
    resource_id = token_row.resource_id
    soldier_id = token_row.soldier_id

    if action == "constraint:approve":
        try:
            constraint_svc.approve_constraint(session, constraint_id=resource_id, actor_id=soldier_id)
            return "✅ בקשת האילוץ אושרה."
        except constraint_svc.ConstraintError as e:
            return f"שגיאה: {e}"

    if action == "exemption:approve":
        try:
            exemption_svc.approve_request(session, request_id=resource_id, decided_by=soldier_id)
            return "✅ בקשת הפטור אושרה."
        except exemption_svc.ExemptionRequestError as e:
            return f"שגיאה: {e}"

    if action == "swap:approve_requester":
        try:
            swap_svc.approve_side(session, request_id=resource_id, side="requester", actor_id=soldier_id)
            return "✅ ההחלפה אושרה מצידך."
        except swap_svc.SwapError as e:
            return f"שגיאה: {e}"

    if action == "swap:approve_covering":
        try:
            swap_svc.claim_request(session, request_id=resource_id, covering_soldier_id=soldier_id, actor_id=soldier_id)
            return "✅ נרשמת כמחליף."
        except swap_svc.SwapError as e:
            return f"שגיאה: {e}"

    return "פעולה לא מוכרת."


def execute_action_with_reason(
    token_row: TelegramActionToken, session: Session, reason: str
) -> str:
    """Execute a reject action with a reason. Returns Hebrew response text."""
    action = token_row.action
    resource_id = token_row.resource_id
    soldier_id = token_row.soldier_id

    if action == "constraint:reject":
        try:
            constraint_svc.reject_constraint(
                session, constraint_id=resource_id, actor_id=soldier_id, decision_note=reason
            )
            return "❌ בקשת האילוץ נדחתה."
        except constraint_svc.ConstraintError as e:
            return f"שגיאה: {e}"

    if action == "exemption:reject":
        try:
            exemption_svc.reject_request(
                session, request_id=resource_id, decided_by=soldier_id, decision_note=reason
            )
            return "❌ בקשת הפטור נדחתה."
        except exemption_svc.ExemptionRequestError as e:
            return f"שגיאה: {e}"

    if action == "swap:reject":
        try:
            swap_svc.reject_request(
                session, request_id=resource_id, decision_note=reason, actor_id=soldier_id
            )
            return "❌ בקשת ההחלפה נדחתה."
        except swap_svc.SwapError as e:
            return f"שגיאה: {e}"

    return "פעולה לא מוכרת."


def execute_silence_step1(
    token_row: TelegramActionToken, session: Session, chat_id: int
) -> str | tuple[str, InlineKeyboardMarkup]:
    """
    Handle the silence button tap.
    - Regular soldiers / non-pending types: immediately set push_enabled=False.
    - Commanders + pending types: return (text, InlineKeyboardMarkup) with depth options.
    """
    from app.db.models import Soldier

    extra = token_row.extra_json or {}
    nt_str = extra.get("notification_type")
    if nt_str is None:
        return "שגיאה: סוג ההתראה חסר."

    nt = NotificationType(nt_str)
    soldier_id = token_row.soldier_id
    soldier = session.get(Soldier, soldier_id)

    if (
        soldier is not None
        and soldier.role in ("commander", "duty_manager", "admin")
        and nt in _DEPTH_TYPES
    ):
        depth_options: list[tuple[str, int | None]] = [
            ("1 – ישיר בלבד", 1),
            ("2", 2),
            ("3", 3),
            ("הכל", None),
        ]
        buttons = [
            InlineKeyboardButton(
                label,
                callback_data=create_token(
                    session,
                    soldier_id=soldier_id,
                    action="silence:depth",
                    extra_json={"notification_type": nt_str, "depth": depth},
                    expiry=DEFAULT_SILENCE_EXPIRY,
                ),
            )
            for label, depth in depth_options
        ]
        markup = InlineKeyboardMarkup([buttons])
        label = _TYPE_LABELS.get(nt_str, nt_str)
        return (f"עד כמה רמות מתחתיך תרצה לקבל התראות על {label}?", markup)

    _set_push_disabled(session, soldier_id=soldier_id, notification_type=nt)
    label = _TYPE_LABELS.get(nt_str, nt_str)
    return f"🔕 התראות {label} בטלגרם הושתקו."


def execute_silence_depth(
    token_row: TelegramActionToken, session: Session, chat_id: int
) -> str:
    """Save commander notification depth preference."""
    extra = token_row.extra_json or {}
    nt_str = extra.get("notification_type")
    depth = extra.get("depth")  # int or None (unlimited)
    soldier_id = token_row.soldier_id

    if nt_str is None:
        return "שגיאה: סוג ההתראה חסר."

    nt = NotificationType(nt_str)
    existing = session.execute(
        select(CommanderNotificationDepth).where(
            CommanderNotificationDepth.commander_id == soldier_id,
            CommanderNotificationDepth.notification_type == nt,
        )
    ).scalar_one_or_none()

    if existing:
        existing.max_depth = depth
    else:
        session.add(CommanderNotificationDepth(
            commander_id=soldier_id,
            notification_type=nt,
            max_depth=depth,
        ))

    if depth is None:
        depth_label = "ללא הגבלה"
    elif depth == 1:
        depth_label = "דיווח ישיר בלבד"
    else:
        depth_label = f"עד {depth} רמות"

    return f"✅ עודכן: תקבל התראות {depth_label}."


def _set_push_disabled(
    session: Session, *, soldier_id: uuid.UUID, notification_type: NotificationType
) -> None:
    pref = session.execute(
        select(NotificationPreference).where(
            NotificationPreference.soldier_id == soldier_id,
            NotificationPreference.notification_type == notification_type,
        )
    ).scalar_one_or_none()
    if pref:
        pref.push_enabled = False
    else:
        session.add(NotificationPreference(
            soldier_id=soldier_id,
            notification_type=notification_type,
            in_app_enabled=True,
            push_enabled=False,
        ))
