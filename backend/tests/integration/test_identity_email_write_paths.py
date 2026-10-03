"""Every Soldier email write path stores canonical email + ad_username together
and reports collisions / unsupported addresses with stable codes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import EmailVerificationToken, Soldier
from app.services import email_verification as ev_svc
from app.services.identity_write import assign_soldier_email
from app.services.invite_codes import create_invite_code
from app.services.soldiers import SoldierValidationError, update_soldier_profile
from tests.helpers import auth_headers, create_node, create_soldier
from tests.integration.test_enrollment_routes import _make_holding, _make_req
from tests.integration.test_registration_routes import _payload, _post_register, _setup_holding


def _uid():
    return uuid.uuid4().hex[:8]


def _owner(session, email, pn=None):
    s = create_soldier(session, personal_number=pn or f"own_{_uid()}")
    assign_soldier_email(session, s, email)
    session.commit()
    return s


def _fresh(session, soldier):
    session.expire_all()
    return session.get(Soldier, soldier.id)


# ── registration ────────────────────────────────────────────────────────────


def _register(client, session, email):
    holding = _setup_holding(session)
    node = create_node(session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(session, uses_left=1, actor_id=None)
    session.commit()
    payload = _payload(invite.code, node.id, email=email)
    return payload, _post_register(client, payload)


def test_registration_stores_canonical_email_and_ad_username(client, admin_session):
    payload, resp = _register(client, admin_session, " Dude@Gmail.COM ")
    assert resp.status_code == 200
    s = admin_session.execute(
        select(Soldier).where(Soldier.personal_number == payload["personal_number"])
    ).scalar_one()
    assert (s.email, s.ad_username, s.email_verified) == ("dude@gmail.com", "dude", False)


@pytest.mark.parametrize(
    ("email", "code"),
    [
        ("not-an-email", "email_invalid"),
        ("a" * 21 + "@example.com", "ad_username_too_long"),
        ("a+b@example.com", "ad_username_invalid"),
    ],
)
def test_registration_rejects_unsupported_email_without_consuming_code(client, admin_session, email, code):
    payload, resp = _register(client, admin_session, email)
    assert resp.status_code == 400
    assert resp.json()["detail"] == code
    assert admin_session.execute(
        select(Soldier).where(Soldier.personal_number == payload["personal_number"])
    ).first() is None


def test_registration_rejects_case_variant_duplicate_email(client, admin_session):
    _owner(admin_session, "dude@gmail.com")
    _payload_, resp = _register(client, admin_session, "DUDE@Gmail.com")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_taken"


def test_registration_rejects_duplicate_ad_username_from_other_domain(client, admin_session):
    _owner(admin_session, "dude@gmail.com")
    _payload_, resp = _register(client, admin_session, "dude@corp.example")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "ad_username_taken"


# ── self-service /me/email ──────────────────────────────────────────────────


def test_me_email_stores_both_fields_and_resets_verification(client, admin_session):
    s = _owner(admin_session, "old@example.com")
    s.email_verified = True
    admin_session.add(EmailVerificationToken(
        soldier_id=s.id, email="old@example.com", token="z" * 48,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    admin_session.commit()
    resp = client.patch("/api/me/email", json={"email": " New.Name@Example.com "}, headers=auth_headers(s))
    assert resp.status_code == 200
    assert resp.json() == {"email_verified": False}
    s = _fresh(admin_session, s)
    assert (s.email, s.ad_username) == ("new.name@example.com", "new.name")
    old = admin_session.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.token == "z" * 48)
    ).scalar_one()
    assert old.used_at is not None


def test_me_email_blank_clears_email_and_ad_username(client, admin_session):
    s = _owner(admin_session, "gone@example.com")
    resp = client.patch("/api/me/email", json={"email": "  "}, headers=auth_headers(s))
    assert resp.status_code == 200
    s = _fresh(admin_session, s)
    assert (s.email, s.ad_username) == (None, None)


def test_me_email_collision_is_409_and_leaves_value_unchanged(client, admin_session):
    _owner(admin_session, "taken@example.com")
    s = _owner(admin_session, "mine@example.com")
    resp = client.patch("/api/me/email", json={"email": "TAKEN@example.com"}, headers=auth_headers(s))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "email_taken"
    s = _fresh(admin_session, s)
    assert (s.email, s.ad_username) == ("mine@example.com", "mine")


def test_me_email_unsupported_address_is_400(client, admin_session):
    s = _owner(admin_session, "mine@example.com")
    resp = client.patch("/api/me/email", json={"email": "a+b@example.com"}, headers=auth_headers(s))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "ad_username_invalid"


# ── enrollment review edit ──────────────────────────────────────────────────


def test_enrollment_edit_stores_both_fields_and_maps_collision(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    _owner(admin_session, "taken@example.com")
    req = _make_req(admin_session, soldier, node)

    ok = client.patch(f"/api/enrollment-requests/{req.id}", json={"email": "Fresh@Example.com"},
                      headers=auth_headers(admin))
    assert ok.status_code == 200
    soldier = _fresh(admin_session, soldier)
    assert (soldier.email, soldier.ad_username) == ("fresh@example.com", "fresh")

    clash = client.patch(f"/api/enrollment-requests/{req.id}", json={"email": "taken@example.com"},
                         headers=auth_headers(admin))
    assert clash.status_code == 409
    assert clash.json()["detail"] == "email_taken"
    bad = client.patch(f"/api/enrollment-requests/{req.id}", json={"email": "nope"},
                       headers=auth_headers(admin))
    assert bad.status_code == 400
    assert bad.json()["detail"] == "email_invalid"
    soldier = _fresh(admin_session, soldier)
    assert soldier.email == "fresh@example.com"


def test_enrollment_edit_personal_number_collision_is_409(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    other = create_soldier(admin_session, personal_number=f"o_{_uid()}")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)
    resp = client.patch(f"/api/enrollment-requests/{req.id}",
                        json={"personal_number": other.personal_number}, headers=auth_headers(admin))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "personal_number_taken"


# ── admin / duty-manager profile edit ───────────────────────────────────────


def test_profile_update_stores_both_fields(admin_session):
    s = create_soldier(admin_session, personal_number=f"pf_{_uid()}")
    update_soldier_profile(admin_session, soldier=s, fields={"email": "Prof.File@Example.com"}, actor_id=None)
    admin_session.commit()
    assert (s.email, s.ad_username) == ("prof.file@example.com", "prof.file")


def test_profile_update_rejects_unsupported_address_and_collision(admin_session):
    from app.services.identity import IdentityCollisionError

    _owner(admin_session, "taken@example.com")
    s = create_soldier(admin_session, personal_number=f"pf_{_uid()}")
    with pytest.raises(SoldierValidationError, match="email_invalid"):
        update_soldier_profile(admin_session, soldier=s, fields={"email": "nope"}, actor_id=None)
    with pytest.raises(IdentityCollisionError):
        update_soldier_profile(admin_session, soldier=s, fields={"email": "Taken@example.com"}, actor_id=None)


def test_profile_route_maps_collision_to_409(client, admin_session):
    node = create_node(admin_session, level="department", name=f"d_{_uid()}")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    s = create_soldier(admin_session, personal_number=f"pf_{_uid()}", hierarchy_node_id=node.id)
    _owner(admin_session, "taken@example.com")
    resp = client.patch(f"/api/soldiers/{s.id}/profile", json={"email": "TAKEN@example.com"},
                        headers=auth_headers(admin))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "email_taken"


# ── email verification ──────────────────────────────────────────────────────


def test_verify_token_accepts_current_canonical_email(admin_session):
    s = _owner(admin_session, "verify@example.com")
    admin_session.add(EmailVerificationToken(
        soldier_id=s.id, email="verify@example.com", token="v" * 48,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    admin_session.commit()
    assert ev_svc.verify_token(admin_session, token="v" * 48) == "ok"
    assert _fresh(admin_session, s).email_verified is True


def test_verify_token_for_legacy_non_canonical_snapshot_still_matches(admin_session):
    s = _owner(admin_session, "verify@example.com")
    admin_session.add(EmailVerificationToken(
        soldier_id=s.id, email=" Verify@Example.com ", token="w" * 48,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    admin_session.commit()
    assert ev_svc.verify_token(admin_session, token="w" * 48) == "ok"


def test_verify_token_rejects_stale_email(admin_session):
    s = _owner(admin_session, "new@example.com")
    admin_session.add(EmailVerificationToken(
        soldier_id=s.id, email="old@example.com", token="x" * 48,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    admin_session.commit()
    assert ev_svc.verify_token(admin_session, token="x" * 48) == "token_invalid"
