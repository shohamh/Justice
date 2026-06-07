from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import PasswordResetToken, TelegramLink
from app.services import password_reset as svc
from tests.helpers import create_soldier


def _link_telegram(session: Session, soldier_id: uuid.UUID, chat_id: int) -> None:
    link = TelegramLink(
        soldier_id=soldier_id,
        telegram_chat_id=chat_id,
        is_verified=True,
        notifications_enabled=True,
    )
    session.add(link)
    session.flush()


def test_available_channels_telegram_only(admin_session: Session):
    s = create_soldier(admin_session, personal_number="PR001")
    _link_telegram(admin_session, s.id, 9001)
    admin_session.flush()

    channels = svc.available_channels(admin_session, personal_number="PR001")
    assert "telegram" in channels
    assert "email" not in channels


def test_available_channels_email_only(admin_session: Session):
    s = create_soldier(admin_session, personal_number="PR002")
    s.email = "test@example.com"
    s.email_verified = True
    admin_session.flush()

    channels = svc.available_channels(admin_session, personal_number="PR002")
    assert "email" in channels
    assert "telegram" not in channels


def test_available_channels_none(admin_session: Session):
    create_soldier(admin_session, personal_number="PR003")
    admin_session.flush()

    channels = svc.available_channels(admin_session, personal_number="PR003")
    assert channels == []


def test_available_channels_unknown_personal_number(admin_session: Session):
    channels = svc.available_channels(admin_session, personal_number="UNKNOWN999")
    assert channels == []


def test_create_token_invalidates_previous(admin_session: Session):
    from sqlalchemy import select
    s = create_soldier(admin_session, personal_number="PR004")
    admin_session.flush()

    token1 = svc._create_reset_token(admin_session, soldier=s, channel="email")
    admin_session.flush()
    token2 = svc._create_reset_token(admin_session, soldier=s, channel="email")
    admin_session.flush()

    old = admin_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token == token1)
    ).scalar_one()
    assert old.used_at is not None  # invalidated
    assert token1 != token2


def test_redeem_token_updates_password(admin_session: Session):
    from app.auth.password import verify_password
    s = create_soldier(admin_session, personal_number="PR005")
    s.email = "pr005@example.com"
    admin_session.flush()

    token = svc._create_reset_token(admin_session, soldier=s, channel="email")
    admin_session.flush()

    result = svc.redeem_reset_token(admin_session, token=token, new_password="NewPass1234!")
    admin_session.flush()

    assert result == "ok"
    assert verify_password("NewPass1234!", s.password_hash)
    assert s.must_change_password is False


def test_redeem_token_expired(admin_session: Session):
    from sqlalchemy import select
    s = create_soldier(admin_session, personal_number="PR006")
    admin_session.flush()

    token_str = "expiredtoken0000000000000000000"
    row = PasswordResetToken(
        soldier_id=s.id,
        token=token_str,
        channel="email",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    admin_session.add(row)
    admin_session.flush()

    result = svc.redeem_reset_token(admin_session, token=token_str, new_password="NewPass1234!")
    assert result == "token_expired"


def test_redeem_token_already_used(admin_session: Session):
    s = create_soldier(admin_session, personal_number="PR007")
    admin_session.flush()

    token = svc._create_reset_token(admin_session, soldier=s, channel="email")
    admin_session.flush()

    svc.redeem_reset_token(admin_session, token=token, new_password="NewPass1234!")
    admin_session.flush()
    result = svc.redeem_reset_token(admin_session, token=token, new_password="AnotherPass1234!")
    assert result == "token_invalid"
