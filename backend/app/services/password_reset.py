from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import PasswordResetToken, Soldier, TelegramLink, TelegramOutbox
from app.services.email import send_email
from app.services.soldiers import PasswordPolicyError, validate_password

_TOKEN_EXPIRY = timedelta(minutes=15)


def available_channels(session: Session, *, personal_number: str) -> list[str]:
    """Return available delivery channels. Returns [] if soldier not found (no enumeration)."""
    soldier = session.execute(
        select(Soldier).where(Soldier.personal_number == personal_number, Soldier.left_at.is_(None))
    ).scalar_one_or_none()
    if soldier is None:
        return []
    channels: list[str] = []
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == soldier.id,
            TelegramLink.is_verified == True,  # noqa: E712
            TelegramLink.telegram_chat_id.isnot(None),
        )
    ).scalar_one_or_none()
    if link is not None:
        channels.append("telegram")
    if soldier.email and soldier.email_verified:
        channels.append("email")
    return channels


def _create_reset_token(session: Session, *, soldier: Soldier, channel: str) -> str:
    """Invalidate existing tokens and create a new one. Returns the token string."""
    now = datetime.now(timezone.utc)
    existing = session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.soldier_id == soldier.id,
            PasswordResetToken.used_at.is_(None),
        )
    ).scalars().all()
    for row in existing:
        row.used_at = now

    token = secrets.token_hex(16)  # 32 hex chars
    row = PasswordResetToken(
        soldier_id=soldier.id,
        token=token,
        channel=channel,
        expires_at=now + _TOKEN_EXPIRY,
    )
    session.add(row)
    session.flush()
    return token


def create_and_send(session: Session, *, personal_number: str, channel: str) -> None:
    """Create a reset token and dispatch it. Silently no-ops if soldier not found."""
    from app.settings import get_settings
    soldier = session.execute(
        select(Soldier).where(Soldier.personal_number == personal_number, Soldier.left_at.is_(None))
    ).scalar_one_or_none()
    if soldier is None:
        return
    channels = available_channels(session, personal_number=personal_number)
    if channel not in channels:
        return

    token = _create_reset_token(session, soldier=soldier, channel=channel)
    settings = get_settings()
    reset_url = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"

    if channel == "telegram":
        link = session.execute(
            select(TelegramLink).where(
                TelegramLink.soldier_id == soldier.id,
                TelegramLink.is_verified == True,  # noqa: E712
                TelegramLink.telegram_chat_id.isnot(None),
            )
        ).scalar_one_or_none()
        if link:
            session.add(TelegramOutbox(
                telegram_chat_id=link.telegram_chat_id,
                message_text=f"קישור לאיפוס סיסמה (תקף ל-15 דקות):\n{reset_url}",
            ))
    elif channel == "email" and soldier.email:
        send_email(
            to=soldier.email,
            subject="איפוס סיסמה — ניהול תורנויות",
            body=f"קישור לאיפוס סיסמה (תקף ל-15 דקות):\n{reset_url}\n\nאם לא ביקשת איפוס סיסמה, התעלם מהודעה זו.",
        )


def redeem_reset_token(session: Session, *, token: str, new_password: str) -> str:
    """Validate token and update password. Returns 'ok', 'token_invalid', 'token_expired', or 'password_too_short'."""
    now = datetime.now(timezone.utc)
    row = session.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == token,
            PasswordResetToken.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        return "token_invalid"
    if row.expires_at <= now:
        return "token_expired"
    try:
        validate_password(new_password)
    except PasswordPolicyError:
        return "password_too_short"
    soldier = session.get(Soldier, row.soldier_id)
    if soldier is None:
        return "token_invalid"
    soldier.password_hash = hash_password(new_password)
    soldier.must_change_password = False
    row.used_at = now
    session.flush()
    return "ok"
