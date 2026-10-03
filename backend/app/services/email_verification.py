from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import EmailVerificationToken, Soldier
from app.services.email import send_email
from app.services.identity import normalize_email

_TOKEN_EXPIRY = timedelta(hours=24)
# Serializes verify_token calls for one email address (see verify_token).
_VERIFIED_EMAIL_LOCK_NAMESPACE = 0x454D4C56  # "EMLV"


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
    # Lock order: soldier, then token row, then the email lock (M1). The
    # email change route (PATCH /me/email) UPDATEs the soldier before
    # request_verification UPDATEs that soldier's unused tokens; locking the
    # token first here and the soldier at flush was the reverse order.
    soldier_id = session.execute(
        select(EmailVerificationToken.soldier_id).where(
            EmailVerificationToken.token == token,
            EmailVerificationToken.used_at.is_(None),
        )
    ).scalar_one_or_none()
    if soldier_id is None:
        return "token_invalid"
    soldier = session.get(Soldier, soldier_id, with_for_update={"key_share": True}, populate_existing=True)
    row = session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token == token,
            EmailVerificationToken.used_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        return "token_invalid"
    if row.expires_at <= now:
        return "token_expired"

    try:
        # Tokens issued before the identity migration snapshot the raw address.
        token_email = normalize_email(row.email)
    except ValueError:
        token_email = None
    if soldier is None or token_email is None or soldier.email != token_email:
        # Soldier changed their email since token was issued
        return "token_invalid"

    # One verified account per email: verify_token is the only writer that
    # sets email_verified=True, so a per-email advisory lock serializes the
    # "already verified by someone else?" check below with the write.
    session.execute(select(func.pg_advisory_xact_lock(_VERIFIED_EMAIL_LOCK_NAMESPACE, func.hashtext(token_email))))

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
