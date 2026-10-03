"""OIDC start/callback endpoints: existing-account login and first-link matching."""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlsplit

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.auth.jwt_tokens import decode_token
from app.db.models import AuditLog, IdentityConflict, OidcIdentity, Soldier
from app.services.oidc import OidcClient, VerifiedIdentity
from app.settings import get_settings
from tests.helpers import create_soldier, set_soldier_email
from tests.support.mock_oidc import ISSUER, MockIdentity, MockOidcProvider
from tests.unit.test_oidc_service import make_config

ERROR_LOCATION = "/login?sso_error=1"


def oidc_dep():
    # Imported lazily: app.rate_limit reads settings at import time, which must
    # happen after the session fixtures point REDIS_URL at the test container.
    from app.routes.oidc import oidc_client_dependency

    return oidc_client_dependency


def frontend(path: str) -> str:
    return get_settings().frontend_url.rstrip("/") + path


@pytest.fixture
def provider(client) -> MockOidcProvider:
    mock = MockOidcProvider()
    oidc_client = OidcClient(make_config(), transport=mock.transport())
    client.app.dependency_overrides[oidc_dep()] = lambda: oidc_client
    yield mock
    client.app.dependency_overrides.pop(oidc_dep(), None)


def sso(client, provider: MockOidcProvider, identity: MockIdentity | None = None):
    """Drive start -> provider -> callback like a browser; returns the callback response."""
    started = client.get("/api/auth/oidc/start", follow_redirects=False)
    assert started.status_code == 302, started.text
    redirect = provider.authorize(started.headers["location"], identity)
    parts = urlsplit(redirect)
    return client.get(f"{parts.path}?{parts.query}", follow_redirects=False)


def add_soldier(session, personal_number: str, email: str | None, **kwargs) -> Soldier:
    soldier = create_soldier(session, personal_number=personal_number, **kwargs)
    if email:
        set_soldier_email(soldier, email)
        session.commit()
    return soldier


def link(session, soldier: Soldier, subject: str = "sub-0001") -> None:
    session.add(OidcIdentity(soldier_id=soldier.id, issuer=ISSUER, subject=subject))
    session.commit()


def assert_denied(response) -> None:
    assert response.status_code == 303
    assert response.headers["location"] == frontend(ERROR_LOCATION)
    assert "refresh_token" not in response.cookies
    assert "refresh_token" not in response.headers.get("set-cookie", "")


# --- availability and start ---------------------------------------------------------


def test_status_reports_enabled(client, provider):
    assert client.get("/api/auth/oidc/status").json() == {"enabled": True}


def test_status_reports_disabled_without_configuration(client):
    client.app.dependency_overrides[oidc_dep()] = lambda: None
    try:
        assert client.get("/api/auth/oidc/status").json() == {"enabled": False}
        assert client.get("/api/auth/oidc/start", follow_redirects=False).status_code == 404
        assert client.get("/api/auth/oidc/callback?code=x&state=y", follow_redirects=False).status_code == 404
    finally:
        client.app.dependency_overrides.pop(oidc_dep(), None)


def test_start_redirects_to_provider_with_pkce_and_binds_the_browser(client, provider):
    response = client.get("/api/auth/oidc/start", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{ISSUER}/authorize?")
    assert "code_challenge_method=S256" in location
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"].lower()
    assert "oidc_txn=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "path=/api/auth/oidc" in cookie


def test_start_discovery_outage_redirects_to_generic_error(client, provider):
    provider.fail_discovery = True
    response = client.get("/api/auth/oidc/start", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == frontend(ERROR_LOCATION)


def test_start_and_callback_are_rate_limited(client, provider, monkeypatch):
    monkeypatch.setenv("OIDC_RATE_LIMIT", "2/minute")
    get_settings.cache_clear()
    try:
        codes = [client.get("/api/auth/oidc/start", follow_redirects=False).status_code for _ in range(4)]
        assert codes[:2] == [302, 302] and codes[-1] == 429
        callbacks = [
            client.get("/api/auth/oidc/callback?code=x&state=y", follow_redirects=False).status_code
            for _ in range(4)
        ]
        assert callbacks[-1] == 429
    finally:
        monkeypatch.delenv("OIDC_RATE_LIMIT")
        get_settings.cache_clear()


# --- existing linked identity ----------------------------------------------------------


def test_linked_identity_logs_in_with_the_existing_session_shape(client, provider, admin_session):
    soldier = add_soldier(admin_session, "6100001", "dude@corp.example", role="commander")
    link(admin_session, soldier)

    response = sso(client, provider)

    assert response.status_code == 303
    assert response.headers["location"] == frontend("/")
    assert "?" not in response.headers["location"]  # nothing sensitive in the URL
    cookie = response.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/api/auth" in cookie
    assert response.headers["cache-control"] == "no-store"

    refreshed = client.post("/api/auth/refresh")  # same cookie the password login sets
    assert refreshed.status_code == 200
    token = decode_token(refreshed.json()["access_token"])
    assert token["sub"] == str(soldier.id) and token["role"] == "commander"

    audit = admin_session.execute(
        select(AuditLog).where(AuditLog.action == "auth.sso.login.success")
    ).scalar_one()
    assert audit.actor_id == soldier.id
    assert "dude" not in str(audit.context)


def test_provider_claims_never_change_authorization(client, provider, admin_session):
    soldier = add_soldier(admin_session, "6100002", "dude@corp.example", role="soldier")
    link(admin_session, soldier)
    provider.token_overrides = {"role": "admin", "groups": ["admins"], "is_admin": True}

    assert sso(client, provider).headers["location"] == frontend("/")
    token = decode_token(client.post("/api/auth/refresh").json()["access_token"])
    assert token["role"] == "soldier"


def test_inactive_linked_soldier_is_denied(client, provider, admin_session):
    from datetime import date

    soldier = add_soldier(admin_session, "6100003", "dude@corp.example")
    link(admin_session, soldier)
    soldier.left_at = date.today()
    admin_session.commit()

    assert_denied(sso(client, provider))


def test_subject_link_survives_an_email_change(client, provider, admin_session):
    soldier = add_soldier(admin_session, "6100004", "new.name@corp.example")
    link(admin_session, soldier, subject="stable-sub")

    response = sso(client, provider, MockIdentity(subject="stable-sub", email="old.name@corp.example"))

    assert response.headers["location"] == frontend("/")
    token = decode_token(client.post("/api/auth/refresh").json()["access_token"])
    assert token["sub"] == str(soldier.id)


def test_linked_subject_is_never_redirected_to_another_soldier_by_email(client, provider, admin_session):
    mine = add_soldier(admin_session, "6100005", "mine@corp.example")
    other = add_soldier(admin_session, "6100006", "other@corp.example")
    link(admin_session, mine, subject="sub-mine")

    sso(client, provider, MockIdentity(subject="sub-mine", email="other@corp.example"))

    token = decode_token(client.post("/api/auth/refresh").json()["access_token"])
    assert token["sub"] == str(mine.id) != str(other.id)


# --- first link --------------------------------------------------------------------------


def test_first_login_links_subject_to_the_matching_soldier(client, provider, admin_session):
    soldier = add_soldier(admin_session, "6100010", "dude@corp.example")

    response = sso(client, provider, MockIdentity(subject="new-sub", email="Dude@Corp.Example"))

    assert response.headers["location"] == frontend("/")
    identity = admin_session.execute(select(OidcIdentity)).scalar_one()
    assert (identity.soldier_id, identity.issuer, identity.subject) == (soldier.id, ISSUER, "new-sub")
    # The next login uses the stable subject, not the email.
    assert sso(client, provider, MockIdentity(subject="new-sub", email="elsewhere@else.example")).headers[
        "location"
    ] == frontend("/")


def test_first_login_of_inactive_soldier_is_denied_and_not_linked(client, provider, admin_session):
    from datetime import date

    soldier = add_soldier(admin_session, "6100011", "dude@corp.example")
    soldier.left_at = date.today()
    admin_session.commit()

    assert_denied(sso(client, provider))
    assert admin_session.execute(select(func.count()).select_from(OidcIdentity)).scalar_one() == 0


def test_soldier_already_linked_to_another_subject_is_denied(client, provider, admin_session):
    soldier = add_soldier(admin_session, "6100012", "dude@corp.example")
    link(admin_session, soldier, subject="first-subject")

    assert_denied(sso(client, provider, MockIdentity(subject="second-subject")))
    rows = admin_session.execute(select(OidcIdentity)).scalars().all()
    assert [r.subject for r in rows] == ["first-subject"]


def test_ambiguous_identity_records_a_conflict_and_denies(client, provider, admin_session):
    # The AD username belongs to a soldier with a different mail domain: the
    # claim matches on one field only, so it is never silently linked.
    a = add_soldier(admin_session, "6100013", "dude@elsewhere.example")
    assert a.ad_username == "dude"

    response = sso(client, provider, MockIdentity(email="dude@corp.example"))

    assert_denied(response)
    conflict = admin_session.execute(select(IdentityConflict)).scalar_one()
    assert (conflict.source, conflict.status, conflict.ad_username) == ("sso", "open", "dude")
    assert admin_session.execute(select(func.count()).select_from(OidcIdentity)).scalar_one() == 0
    assert "dude" not in response.headers["location"]


def test_unmatched_identity_creates_no_soldier_and_no_session(client, provider, admin_session):
    before = admin_session.execute(select(func.count()).select_from(Soldier)).scalar_one()
    response = sso(client, provider, MockIdentity(email="stranger@corp.example"))
    assert "refresh_token" not in response.cookies
    assert admin_session.execute(select(func.count()).select_from(Soldier)).scalar_one() == before
    assert admin_session.execute(select(func.count()).select_from(OidcIdentity)).scalar_one() == 0


# --- callback validation ---------------------------------------------------------------------


def test_callback_replay_is_denied(client, provider, admin_session):
    soldier = add_soldier(admin_session, "6100020", "dude@corp.example")
    link(admin_session, soldier)
    started = client.get("/api/auth/oidc/start", follow_redirects=False)
    parts = urlsplit(provider.authorize(started.headers["location"]))
    url = f"{parts.path}?{parts.query}"

    assert client.get(url, follow_redirects=False).headers["location"] == frontend("/")
    client.cookies.delete("refresh_token")
    assert_denied(client.get(url, follow_redirects=False))


def test_callback_from_a_different_browser_is_denied(client, provider, admin_session):
    soldier = add_soldier(admin_session, "6100021", "dude@corp.example")
    link(admin_session, soldier)
    started = client.get("/api/auth/oidc/start", follow_redirects=False)
    parts = urlsplit(provider.authorize(started.headers["location"]))
    client.cookies.clear()  # the attacker's browser has no transaction cookie

    assert_denied(client.get(f"{parts.path}?{parts.query}", follow_redirects=False))


def test_callback_with_unknown_state_is_denied(client, provider):
    client.get("/api/auth/oidc/start", follow_redirects=False)
    assert_denied(client.get("/api/auth/oidc/callback?code=abc&state=forged", follow_redirects=False))


def test_callback_without_code_or_with_provider_error_is_denied_and_burns_the_transaction(
    client, provider, admin_session
):
    soldier = add_soldier(admin_session, "6100022", "dude@corp.example")
    link(admin_session, soldier)
    started = client.get("/api/auth/oidc/start", follow_redirects=False)
    good = urlsplit(provider.authorize(started.headers["location"]))
    state = [p for p in good.query.split("&") if p.startswith("state=")][0]

    assert_denied(client.get(f"/api/auth/oidc/callback?error=access_denied&{state}", follow_redirects=False))
    assert_denied(client.get(f"{good.path}?{good.query}", follow_redirects=False))


@pytest.mark.parametrize(
    "tamper",
    [
        {"token_overrides": {"iss": "https://evil.example.test"}},
        {"token_overrides": {"aud": "someone-else"}},
        {"token_overrides": {"nonce": "forged-nonce"}},
        {"sign_with_foreign_key": True},
        {"drop_claims": {"email_verified"}},
        {"fail_token": True},
        {"fail_jwks": True},
    ],
)
def test_invalid_provider_responses_never_create_a_session(client, provider, admin_session, tamper):
    soldier = add_soldier(admin_session, "6100023", "dude@corp.example")
    link(admin_session, soldier)
    for name, value in tamper.items():
        setattr(provider, name, value)

    assert_denied(sso(client, provider))
    assert client.post("/api/auth/refresh").status_code == 401


def test_logs_and_audit_never_contain_codes_state_nonce_subject_or_email(
    client, provider, admin_session, caplog
):
    caplog.set_level(logging.DEBUG)
    soldier = add_soldier(admin_session, "6100024", "dude@corp.example")
    link(admin_session, soldier, subject="very-secret-subject")
    started = client.get("/api/auth/oidc/start", follow_redirects=False)
    redirect = provider.authorize(started.headers["location"], MockIdentity(subject="very-secret-subject"))
    query = urlsplit(redirect).query
    client.get(f"/api/auth/oidc/callback?{query}", follow_redirects=False)  # success
    provider.token_overrides = {"iss": "https://evil.example.test"}
    sso(client, provider)  # failure path

    code = [p.split("=")[1] for p in query.split("&") if p.startswith("code=")][0]
    haystack = caplog.text + " ".join(str(a.context) + str(a.after) + str(a.before) for a in
                                      admin_session.execute(select(AuditLog)).scalars())
    for secret in (code, "very-secret-subject", "dude@corp.example", "mock-access-token"):
        assert secret not in haystack


# --- concurrency at the service layer ----------------------------------------------------------


def _identity(subject: str, email: str = "dude@corp.example") -> VerifiedIdentity:
    return VerifiedIdentity(issuer=ISSUER, subject=subject, email=email)


def _run_concurrently(admin_engine, identities: list[VerifiedIdentity]) -> list[str]:
    factory = sessionmaker(bind=admin_engine, expire_on_commit=False)
    barrier = threading.Barrier(len(identities))
    outcomes: list[str] = []

    def worker(identity: VerifiedIdentity) -> None:
        with factory() as session:
            barrier.wait()
            from app.services.oidc_login import authenticate

            result = authenticate(session, identity)
            session.commit()
            outcomes.append(result.kind)

    threads = [threading.Thread(target=worker, args=(i,)) for i in identities]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return outcomes


def test_concurrent_first_logins_of_one_subject_link_once(admin_engine, admin_session):
    soldier = add_soldier(admin_session, "6100030", "dude@corp.example")
    outcomes = _run_concurrently(admin_engine, [_identity("same-sub")] * 4)
    assert outcomes == ["login"] * 4
    rows = admin_session.execute(select(OidcIdentity)).scalars().all()
    assert [(r.soldier_id, r.subject) for r in rows] == [(soldier.id, "same-sub")]


def test_concurrent_first_logins_of_two_subjects_for_one_soldier_link_only_one(admin_engine, admin_session):
    add_soldier(admin_session, "6100031", "dude@corp.example")
    outcomes = _run_concurrently(admin_engine, [_identity("sub-a"), _identity("sub-b")])
    assert sorted(outcomes) == ["denied", "login"]
    assert admin_session.execute(select(func.count()).select_from(OidcIdentity)).scalar_one() == 1


# --- storage constraints --------------------------------------------------------------------------


def test_database_rejects_duplicate_subject_and_second_identity_per_soldier(admin_session):
    a = add_soldier(admin_session, "6100040", "a@corp.example")
    b = add_soldier(admin_session, "6100041", "b@corp.example")
    admin_session.add(OidcIdentity(soldier_id=a.id, issuer=ISSUER, subject="s1"))
    admin_session.commit()

    admin_session.add(OidcIdentity(soldier_id=b.id, issuer=ISSUER, subject="s1"))
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()

    admin_session.add(OidcIdentity(soldier_id=a.id, issuer=ISSUER, subject="s2"))
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()

    admin_session.add(OidcIdentity(soldier_id=b.id, issuer="https://other.example.test", subject="s1"))
    admin_session.commit()  # same subject under a different issuer is a different identity
