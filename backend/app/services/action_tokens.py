from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TelegramActionToken, TelegramLink

DEFAULT_ACTION_EXPIRY = timedelta(minutes=10)
DEFAULT_SILENCE_EXPIRY = timedelta(minutes=30)


def create_token(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    action: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    extra_json: dict | None = None,
    expiry: timedelta = DEFAULT_ACTION_EXPIRY,
) -> str:
    token = secrets.token_hex(8)  # 16 hex chars
    t = TelegramActionToken(
        token=token,
        soldier_id=soldier_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        extra_json=extra_json,
        expires_at=datetime.now(timezone.utc) + expiry,
    )
    session.add(t)
    session.flush()
    return token


def redeem_token(session: Session, *, token: str, chat_id: int) -> TelegramActionToken | None:
    """Validate and consume a token. Returns the row or None if invalid/expired/used/wrong chat."""
    now = datetime.now(timezone.utc)
    t = session.execute(
        select(TelegramActionToken).where(
            TelegramActionToken.token == token,
            TelegramActionToken.used_at.is_(None),
            TelegramActionToken.expires_at > now,
        )
    ).scalar_one_or_none()
    if t is None:
        return None
    link = session.execute(
        select(TelegramLink).where(
            TelegramLink.soldier_id == t.soldier_id,
            TelegramLink.telegram_chat_id == chat_id,
            TelegramLink.is_verified == True,  # noqa: E712
        )
    ).scalar_one_or_none()
    if link is None:
        return None
    t.used_at = now
    session.flush()
    return t


def set_awaiting_reply(session: Session, *, token: str, chat_id: int) -> bool:
    """Mark a token as waiting for a free-text reply from chat_id. Returns True if found."""
    t = session.execute(
        select(TelegramActionToken).where(
            TelegramActionToken.token == token,
            TelegramActionToken.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if t is None:
        return False
    t.awaiting_text_from_chat_id = chat_id
    session.flush()
    return True


def find_pending_reply(session: Session, *, chat_id: int) -> TelegramActionToken | None:
    """Return the pending-reply token for this chat, or None."""
    now = datetime.now(timezone.utc)
    return session.execute(
        select(TelegramActionToken).where(
            TelegramActionToken.awaiting_text_from_chat_id == chat_id,
            TelegramActionToken.used_at.is_(None),
            TelegramActionToken.expires_at > now,
        )
    ).scalar_one_or_none()


def cleanup_expired(session: Session) -> int:
    """Delete tokens older than 24 h. Returns count deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = list(
        session.execute(
            select(TelegramActionToken).where(TelegramActionToken.created_at < cutoff)
        ).scalars().all()
    )
    for r in rows:
        session.delete(r)
    return len(rows)
