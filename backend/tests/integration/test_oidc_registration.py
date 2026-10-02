"""Unmatched SSO identities continue into registration without an invite code."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import (
    AuditLog,
    IdentityConflict,
    OidcIdentity,
    OidcRegistrationContext,
    RegistrationInviteCode,
    Soldier,
    SoldierEnrollmentRequest,
)
from app.services.oidc import OidcClient
from tests.helpers import auth_headers, create_node, create_soldier, set_soldier_email
from tests.integration.test_oidc_login_routes import frontend
from tests.integration.test_registration_routes import _payload, _post_register, _setup_holding
from tests.support.mock_oidc import ISSUER, MockIdentity, MockOidcProvider
from tests.unit.test_oidc_service import make_config

STRANGER = MockIdentity(subject="stranger-sub", email="Stranger@Corp.Example")
GENERIC = "registration_unavailable"


def oidc_dep():
    from app.routes.oidc import oidc_client_dependency

    return oidc_client_dependency


@pytest.fixture
def provider(client) -> MockOidcProvider:
    mock = MockOidcProvider()
    oidc_client = OidcClient(make_config(), transport=mock.transport())
    client.app.dependency_overrides[oidc_dep()] = lambda: oidc_client
    yield mock
    client.app.dependency_overrides.pop(oidc_dep(), None)


def callback(client, provider, identity=STRANGER):
    started = client.get("/api/auth/oidc/start", follow_redirects=False)
    parts = urlsplit(provider.authorize(started.headers["location"], identity))
    return client.get(f"{parts.path}?{parts.query}", follow_redirects=False)


@pytest.fixture
def world(admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name="sso-unit", parent=holding)
    admin_session.commit()
    return holding, node


def register(client, node, **overrides):
    return _post_register(client, _payload("", node.id, **overrides))


def count(session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


# --- callback creates a context, never a soldier -----------------------------------------


def test_unmatched_identity_creates_context_not_soldier(client, provider, admin_session, world):
    before = count(admin_session, Soldier)
    response = callback(client, provider)

    assert response.status_code == 303
    assert response.headers["location"] == frontend("/register?sso=1")
    assert "stranger" not in response.headers["location"].lower()
    cookie = response.headers["set-cookie"].lower()
    assert "oidc_reg=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "refresh_token" not in response.headers["set-cookie"]
    assert count(admin_session, Soldier) == before
    assert count(admin_session, OidcIdentity) == 0

    context = admin_session.execute(select(OidcRegistrationContext)).scalar_one()
    assert (context.issuer, context.subject) == (ISSUER, "stranger-sub")
    assert (context.email, context.ad_username) == ("stranger@corp.example", "stranger")
    assert context.consumed_at is None
    token = client.cookies.get("oidc_reg")
    assert token and token not in (context.token_hash,)
    ttl = context.expires_at - context.created_at
    assert timedelta(minutes=14) < ttl <= timedelta(minutes=15, seconds=2)


def test_repeated_callbacks_keep_one_live_context_per_subject(client, provider, admin_session, world):
    callback(client, provider)
    callback(client, provider)
    assert count(admin_session, OidcRegistrationContext) == 1


def test_registration_context_endpoint_returns_only_prefill_values(client, provider, world):
    assert client.get("/api/auth/oidc/registration-context").status_code == 404
    callback(client, provider)
    response = client.get("/api/auth/oidc/registration-context")
    assert response.status_code == 200
    assert response.json() == {"email": "stranger@corp.example", "ad_username": "stranger"}
    assert response.headers["cache-control"] == "no-store"


def test_registration_context_is_not_available_to_another_browser(client, provider, world):
    callback(client, provider)
    other = TestClient(client.app)
    assert other.get("/api/auth/oidc/registration-context").status_code == 404
    other.cookies.set("oidc_reg", "forged-value")
    assert other.get("/api/auth/oidc/registration-context").status_code == 404


def test_nodes_listing_needs_invite_code_or_live_context(client, provider, world):
    assert client.get("/api/auth/register/nodes").status_code == 422
    assert client.get("/api/auth/register/nodes?invite_code=nope").status_code == 403
    callback(client, provider)
    assert client.get("/api/auth/register/nodes").status_code == 200


# --- final registration -----------------------------------------------------------------------


def test_registration_without_invite_code_through_context(client, provider, admin_session, world):
    holding, node = world
    callback(client, provider)

    response = register(client, node, email="forged@elsewhere.example")

    assert response.status_code == 200, response.text
    assert "refresh_token" in response.cookies
    soldier = admin_session.execute(select(Soldier).where(Soldier.email.is_not(None))).scalar_one()
    # Email and username come from the verified context, not from the request body.
    assert (soldier.email, soldier.ad_username) == ("stranger@corp.example", "stranger")
    assert soldier.email_verified is True
    assert soldier.role == "soldier" and soldier.hierarchy_node_id == holding.id
    identity = admin_session.execute(select(OidcIdentity)).scalar_one()
    assert (identity.soldier_id, identity.issuer, identity.subject) == (soldier.id, ISSUER, "stranger-sub")
    enrollment = admin_session.execute(select(SoldierEnrollmentRequest)).scalar_one()
    assert (enrollment.soldier_id, enrollment.requested_node_id, enrollment.status) == (
        soldier.id, node.id, "pending",
    )
    context = admin_session.execute(select(OidcRegistrationContext)).scalar_one()
    assert context.consumed_at is not None
    assert count(admin_session, RegistrationInviteCode) == 0
    # The cookie is spent and the session works like a normal registration session.
    assert 'oidc_reg=""' in response.headers["set-cookie"] or "oidc_reg=;" in response.headers["set-cookie"]
    assert client.post("/api/auth/refresh").status_code == 200


def test_sso_registered_soldier_waits_in_holding_until_a_mador_commander_approves(
    client, provider, admin_session, world
):
    holding, _unit = world
    group = create_node(admin_session, level="group", name="sso-group", parent=holding)
    node = create_node(admin_session, level="team", name="sso-team", parent=group)
    unit_commander = create_soldier(admin_session, personal_number="7770001", role="commander")
    node.commander_id = unit_commander.id
    group_commander = create_soldier(admin_session, personal_number="7770003", role="commander")
    group.commander_id = group_commander.id
    admin_session.commit()
    callback(client, provider)
    assert register(client, node).status_code == 200
    soldier = admin_session.execute(select(Soldier).where(Soldier.email.is_not(None))).scalar_one()
    request_row = admin_session.execute(select(SoldierEnrollmentRequest)).scalar_one()
    approve = f"/api/enrollment-requests/{request_row.id}/approve"

    # Pending: in the holding node, plain role, and unable to approve themselves.
    assert soldier.hierarchy_node_id == holding.id and soldier.role == "soldier"
    assert client.post(approve, headers=auth_headers(soldier), json={}).status_code == 403
    bystander = create_soldier(admin_session, personal_number="7770002")
    assert client.post(approve, headers=auth_headers(bystander), json={}).status_code == 403
    # A commander below mador level (team) may approve ordinary enrollments but not SSO sign-ups.
    denied = client.post(approve, headers=auth_headers(unit_commander), json={})
    assert denied.status_code == 403 and denied.json()["detail"] == "sso_approval_requires_mador"
    admin_session.refresh(soldier)
    assert soldier.hierarchy_node_id == holding.id

    assert client.post(approve, headers=auth_headers(group_commander), json={}).status_code == 200
    admin_session.refresh(soldier)
    assert soldier.hierarchy_node_id == node.id


def test_plain_registration_still_requires_the_invite_code(client, world):
    _holding, node = world
    response = register(client, node)
    assert response.status_code == 400
    assert admin_count(client) == 0


def admin_count(client) -> int:
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        return count(session, Soldier)


@pytest.mark.parametrize("flag", ["sso", "skip_invite", "oidc", "invite_code_waived"])
def test_client_flags_cannot_waive_the_invite_code(client, world, flag):
    _holding, node = world
    payload = _payload("", node.id, **{flag: True})
    response = _post_register(client, payload)
    assert response.status_code == 400
    assert admin_count(client) == 0


def test_forged_cookie_cannot_waive_the_invite_code(client, world):
    _holding, node = world
    client.cookies.set("oidc_reg", "a-forged-context-token")
    assert register(client, node).status_code == 400
    assert admin_count(client) == 0


def test_expired_context_cannot_waive_the_invite_code(client, provider, admin_session, world):
    _holding, node = world
    callback(client, provider)
    context = admin_session.execute(select(OidcRegistrationContext)).scalar_one()
    context.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    admin_session.commit()

    assert register(client, node).status_code == 400
    assert client.get("/api/auth/oidc/registration-context").status_code == 404
    assert count(admin_session, Soldier) == 0 and count(admin_session, OidcIdentity) == 0


def test_replayed_context_is_rejected(client, provider, admin_session, world):
    _holding, node = world
    callback(client, provider)
    token = client.cookies.get("oidc_reg")
    assert register(client, node).status_code == 200

    replay = TestClient(client.app)
    replay.cookies.set("oidc_reg", token)
    assert register(replay, node).status_code == 400
    assert count(admin_session, Soldier) == 1


def test_context_from_another_browser_is_rejected(client, provider, admin_session, world):
    _holding, node = world
    callback(client, provider)
    attacker = TestClient(client.app)  # no cookie
    assert register(attacker, node).status_code == 400
    assert count(admin_session, Soldier) == 0


def test_context_can_be_retried_after_a_validation_failure(client, provider, admin_session, world):
    _holding, node = world
    owner = create_soldier(admin_session, personal_number="7770003")
    callback(client, provider)

    taken = register(client, node, personal_number=owner.personal_number)
    assert taken.status_code == 400 and taken.json()["detail"] == GENERIC
    assert count(admin_session, Soldier) == 1  # only the pre-existing owner
    assert count(admin_session, OidcIdentity) == 0

    bad_dates = register(client, node, discharge_date="2000-01-01")
    assert bad_dates.status_code == 400
    assert count(admin_session, OidcIdentity) == 0

    assert register(client, node, personal_number="7770004").status_code == 200


def test_personal_number_is_still_required(client, provider, world):
    _holding, node = world
    callback(client, provider)
    payload = _payload("", node.id)
    del payload["personal_number"]
    assert _post_register(client, payload).status_code == 422
    payload = _payload("", node.id, personal_number="12")
    assert _post_register(client, payload).status_code == 422


def test_password_is_still_required(client, provider, world):
    _holding, node = world
    callback(client, provider)
    payload = _payload("", node.id)
    del payload["password"]
    assert _post_register(client, payload).status_code == 422
    assert register(client, node, password="short").status_code == 422


def test_email_taken_after_callback_is_refused_generically_with_a_conflict(
    client, provider, admin_session, world
):
    _holding, node = world
    callback(client, provider)
    owner = create_soldier(admin_session, personal_number="7770005")
    set_soldier_email(owner, "stranger@corp.example")
    admin_session.commit()

    response = register(client, node)

    assert response.status_code == 400 and response.json()["detail"] == GENERIC
    assert count(admin_session, OidcIdentity) == 0
    assert count(admin_session, Soldier) == 1
    conflict = admin_session.execute(select(IdentityConflict)).scalar_one()
    assert (conflict.source, conflict.status, conflict.ad_username) == ("registration", "open", "stranger")


def test_username_owned_by_other_domain_after_callback_is_ambiguous(client, provider, admin_session, world):
    _holding, node = world
    callback(client, provider)
    owner = create_soldier(admin_session, personal_number="7770006")
    set_soldier_email(owner, "stranger@other.example")
    admin_session.commit()

    response = register(client, node)

    assert response.status_code == 400 and response.json()["detail"] == GENERIC
    assert admin_session.execute(select(IdentityConflict)).scalar_one().source == "registration"
    assert count(admin_session, OidcIdentity) == 0


def test_subject_already_linked_after_callback_is_refused(client, provider, admin_session, world):
    _holding, node = world
    callback(client, provider)
    other = create_soldier(admin_session, personal_number="7770007")
    admin_session.add(OidcIdentity(soldier_id=other.id, issuer=ISSUER, subject="stranger-sub"))
    admin_session.commit()

    response = register(client, node)

    assert response.status_code == 400 and response.json()["detail"] == GENERIC
    assert count(admin_session, Soldier) == 1
    ctx = admin_session.execute(select(OidcRegistrationContext)).scalar_one()
    assert ctx.consumed_at is None


def test_errors_do_not_reveal_which_value_collided(client, provider, admin_session, world):
    _holding, node = world
    owner = create_soldier(admin_session, personal_number="7770008")
    callback(client, provider)
    by_personal_number = register(client, node, personal_number=owner.personal_number)
    set_soldier_email(owner, "stranger@corp.example")
    admin_session.commit()
    by_email = register(client, node, personal_number="7770009")
    assert by_personal_number.json() == by_email.json() == {"detail": GENERIC}


def test_concurrent_registrations_with_one_context_create_one_soldier(client, provider, admin_session, world):
    _holding, node = world
    callback(client, provider)
    token = client.cookies.get("oidc_reg")
    statuses: list[int] = []
    barrier = threading.Barrier(3)

    def worker(index: int) -> None:
        browser = TestClient(client.app)
        browser.cookies.set("oidc_reg", token)
        barrier.wait()
        statuses.append(register(browser, node, personal_number=f"778000{index}").status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(statuses) == [200, 400, 400]
    assert count(admin_session, Soldier) == 1 and count(admin_session, OidcIdentity) == 1


def test_no_pii_or_tokens_in_logs_or_audit(client, provider, admin_session, world, caplog):
    _holding, node = world
    caplog.set_level(logging.DEBUG)
    callback(client, provider)
    token = client.cookies.get("oidc_reg")
    register(client, node)
    haystack = caplog.text + json.dumps(
        [str(a.context) + str(a.before) + str(a.after) for a in admin_session.execute(select(AuditLog)).scalars()]
    )
    for secret in (token, "stranger@corp.example", "stranger-sub"):
        assert secret not in haystack
