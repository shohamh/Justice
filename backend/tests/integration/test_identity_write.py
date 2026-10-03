"""Shared soldier identity write helpers (email + derived AD username)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import EmailVerificationToken, Soldier
from app.services.identity import IdentityCollisionError
from app.services.identity_write import (
    assign_soldier_email,
    check_personal_number_available,
    flush_with_identity_guard,
    resolve_identity_fields,
)
from tests.helpers import create_soldier


def _make(session, pn, email=None):
    s = create_soldier(session, personal_number=pn)
    if email is not None:
        assign_soldier_email(session, s, email)
        session.commit()
    return s


def test_resolve_identity_fields_normalizes_and_returns_both(admin_session):
    assert resolve_identity_fields(admin_session, " Dude@Gmail.COM ") == ("dude@gmail.com", "dude")
    assert resolve_identity_fields(admin_session, "  ") == (None, None)
    assert resolve_identity_fields(admin_session, None) == (None, None)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("nope", "email_invalid"),
        ("a" * 21 + "@example.com", "ad_username_too_long"),
        ("a+b@example.com", "ad_username_invalid"),
    ],
)
def test_resolve_identity_fields_rejects_unsupported_values(admin_session, raw, code):
    with pytest.raises(ValueError, match=code) as excinfo:
        resolve_identity_fields(admin_session, raw)
    assert not isinstance(excinfo.value, IdentityCollisionError)


def test_resolve_identity_fields_detects_email_collision_case_insensitively(admin_session):
    _make(admin_session, "iw-1", "Dude@Gmail.com")
    with pytest.raises(IdentityCollisionError) as excinfo:
        resolve_identity_fields(admin_session, " dude@GMAIL.com")
    assert excinfo.value.field == "email"


def test_resolve_identity_fields_detects_ad_username_collision_across_domains(admin_session):
    _make(admin_session, "iw-1", "dude@gmail.com")
    with pytest.raises(IdentityCollisionError) as excinfo:
        resolve_identity_fields(admin_session, "dude@corp.example")
    assert excinfo.value.field == "ad_username"


def test_resolve_identity_fields_excludes_the_soldier_itself(admin_session):
    s = _make(admin_session, "iw-1", "dude@gmail.com")
    assert resolve_identity_fields(admin_session, "DUDE@gmail.com", exclude_soldier_id=s.id) == (
        "dude@gmail.com",
        "dude",
    )


def test_assign_stores_both_fields_and_clears_verification_on_change(admin_session):
    s = _make(admin_session, "iw-1", "old@example.com")
    s.email_verified = True
    token = EmailVerificationToken(
        soldier_id=s.id,
        email="old@example.com",
        token="t" * 48,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    admin_session.add(token)
    admin_session.commit()

    assert assign_soldier_email(admin_session, s, " New.Name@Example.com ") is True
    admin_session.commit()
    admin_session.refresh(s)
    admin_session.refresh(token)
    assert (s.email, s.ad_username, s.email_verified) == ("new.name@example.com", "new.name", False)
    assert token.used_at is not None  # outstanding token invalidated


def test_assign_same_canonical_email_is_a_noop_and_keeps_verification(admin_session):
    s = _make(admin_session, "iw-1", "same@example.com")
    s.email_verified = True
    admin_session.commit()
    assert assign_soldier_email(admin_session, s, " SAME@example.com") is False
    assert s.email_verified is True


def test_assign_blank_clears_both_fields(admin_session):
    s = _make(admin_session, "iw-1", "gone@example.com")
    assert assign_soldier_email(admin_session, s, "   ") is True
    assert (s.email, s.ad_username, s.email_verified) == (None, None, False)


def test_assign_collision_leaves_soldier_unchanged(admin_session):
    _make(admin_session, "iw-1", "taken@example.com")
    s = _make(admin_session, "iw-2", "mine@example.com")
    with pytest.raises(IdentityCollisionError):
        assign_soldier_email(admin_session, s, "taken@example.com")
    assert (s.email, s.ad_username) == ("mine@example.com", "mine")


def test_assign_can_preserve_issuer_verified_status(admin_session):
    s = _make(admin_session, "iw-1")
    assign_soldier_email(admin_session, s, "sso@example.com", verified=True)
    assert s.email_verified is True


def test_flush_guard_translates_race_to_typed_error_naming_the_field(admin_session):
    _make(admin_session, "iw-1", "race@example.com")
    # Simulate a concurrent writer that slipped past the application check.
    loser = Soldier(
        personal_number="iw-2", full_name="x y", password_hash="h",
        email="race@example.com", ad_username="race",
    )
    admin_session.add(loser)
    with pytest.raises(IdentityCollisionError) as excinfo:
        flush_with_identity_guard(admin_session)
    assert excinfo.value.field in {"email", "ad_username"}
    admin_session.rollback()

    dup_pn = Soldier(personal_number="iw-1", full_name="x y", password_hash="h")
    admin_session.add(dup_pn)
    with pytest.raises(IdentityCollisionError) as excinfo:
        flush_with_identity_guard(admin_session)
    assert excinfo.value.field == "personal_number"
    admin_session.rollback()


def test_flush_guard_does_not_swallow_unrelated_integrity_errors(admin_session):
    from sqlalchemy.exc import IntegrityError

    admin_session.add(Soldier(personal_number="iw-9", full_name="x y", password_hash=None))
    with pytest.raises(IntegrityError):
        flush_with_identity_guard(admin_session)
    admin_session.rollback()


def test_check_personal_number_available(admin_session):
    s = _make(admin_session, "iw-1")
    with pytest.raises(IdentityCollisionError) as excinfo:
        check_personal_number_available(admin_session, "iw-1")
    assert excinfo.value.field == "personal_number"
    check_personal_number_available(admin_session, "iw-1", exclude_soldier_id=s.id)
    check_personal_number_available(admin_session, "iw-2")
    assert admin_session.execute(select(Soldier.id).where(Soldier.personal_number == "iw-2")).first() is None
