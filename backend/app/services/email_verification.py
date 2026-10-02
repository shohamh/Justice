from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EmailVerificationToken, Soldier
from app.services.email import send_email
from app.services.identity import normalize_email

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
    try:
        # Tokens issued before the identity migration snapshot the raw address.
        token_email = normalize_email(row.email)
    except ValueError:
        token_email = None
    if soldier is None or token_email is None or soldier.email != token_email:
        # Soldier changed their email since token was issued
        return "token_invalid"

    # Email is unique across verified and unverified rows (database-enforced);
    # this guards legacy data and keeps the redeem result explicit.
    conflict = session.execute(
        select(Soldier.id).where(Soldier.email == token_email, Soldier.id != soldier.id).limit(1)
    ).first()
    if conflict is not None:
        return "email_taken"

    soldier.email_verified = True
    row.used_at = now
    session.flush()
    return "ok"
