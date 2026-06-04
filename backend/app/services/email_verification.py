from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EmailVerificationToken, Soldier
from app.services.email import send_email

_TOKEN_EXPIRY = timedelta(hours=24)


def request_verification(session: Session, *, soldier: Soldier) -> bool:
    """Create a verification token and send it. Returns False if no email set or SMTP unconfigured."""
    if not soldier.email:
        return False

    now = datetime.now(timezone.utc)
    # Invalidate any existing unused tokens for this soldier
    existing = session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.soldier_id == soldier.id,
            EmailVerificationToken.used_at.is_(None),
        )
    ).scalars().all()
    for row in existing:
        row.used_at = now

    token = secrets.token_hex(24)  # 48 hex chars
    row = EmailVerificationToken(
        soldier_id=soldier.id,
        email=soldier.email,
        token=token,
        expires_at=now + _TOKEN_EXPIRY,
    )
    session.add(row)
    session.flush()

    from app.settings import get_settings
    settings = get_settings()
    verify_url = f"{settings.frontend_url.rstrip('/')}/verify-email?token={token}"

    return send_email(
        to=soldier.email,
        subject="אימות כתובת אימייל — ניהול תורנויות",
        body=f"לאימות כתובת האימייל שלך לחץ על הקישור (תקף ל-24 שעות):\n{verify_url}\n\nאם לא ביקשת אימות, התעלם מהודעה זו.",
    )


def verify_token(session: Session, *, token: str) -> str:
    """Redeem a verification token. Returns 'ok', 'token_invalid', 'token_expired', or 'email_taken'."""
    now = datetime.now(timezone.utc)
    row = session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token == token,
            EmailVerificationToken.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        return "token_invalid"
    if row.expires_at <= now:
        return "token_expired"

    soldier = session.get(Soldier, row.soldier_id)
    if soldier is None or soldier.email != row.email:
        # Soldier changed their email since token was issued
        return "token_invalid"

    # Check no other soldier has already verified this email
    conflict = session.execute(
        select(Soldier).where(
            Soldier.email == row.email,
            Soldier.email_verified == True,  # noqa: E712
            Soldier.id != soldier.id,
        )
    ).scalar_one_or_none()
    if conflict is not None:
        return "email_taken"

    soldier.email_verified = True
    row.used_at = now
    session.flush()
    return "ok"
