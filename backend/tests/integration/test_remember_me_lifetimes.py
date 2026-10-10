"""Remember-me by default (90 days); unticked means short sliding session tokens.

- default / remember_me=true -> persistent cookie, JWT exp ~ refresh_token_days
- remember_me=false -> session cookie AND a short JWT exp (session_refresh_token_hours),
  re-issued fresh on every rotation (sliding); an idle one expires.
- OIDC carries the choice in the browser-bound transaction token (tamper-proof).
"""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy.orm import Session

from app.auth import jwt_tokens, refresh_revocation
from app.auth.jwt_tokens import decode_token, issue_refresh_token
from app.redis_client import get_redis
from app.settings import get_settings
from tests.helpers import create_soldier

_PASSWORD = "password-1234"
_DAY = 24 * 3600


def _login(client, pn: str, **extra):
    client.cookies.clear()
    r = client.post(
        "/api/auth/login", json={"personal_number": pn, "password": _PASSWORD, **extra}
    )
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r


def _refresh(client, cookie: str):
    client.cookies.clear()
    r = client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={cookie}"})
    client.cookies.clear()
    return r


def _set_cookie(response) -> str:
    headers = [h for h in response.headers.get_list("set-cookie") if h.startswith("refresh_token=")]
    assert len(headers) == 1
    return headers[0].lower()


def _is_session(response) -> bool:
    h = _set_cookie(response)
    return "max-age" not in h and "expires" not in h


def _remaining(token: str) -> int:
    return decode_token(token)["exp"] - int(time.time())


@pytest.fixture
def soldier(admin_session: Session):
    s = create_soldier(admin_session, personal_number="7830001", password=_PASSWORD)
    admin_session.commit()
    return s


def test_defaults():
    s = get_settings()
    assert s.refresh_token_days == 90
    assert s.session_refresh_token_hours == 12


def test_login_without_flag_is_remembered_for_90_days(client, soldier):
    r = _login(client, soldier.personal_number)
    assert f"max-age={90 * _DAY}" in _set_cookie(r)
    assert f"max-age={get_settings().refresh_token_days * _DAY}" in _set_cookie(r)
    cookie = r.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is True
    assert abs(_remaining(cookie) - 90 * _DAY) < 30


def test_unticked_login_is_session_cookie_with_short_exp(client, soldier):
    r = _login(client, soldier.personal_number, remember_me=False)
    assert _is_session(r)
    cookie = r.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is False
    hours = get_settings().session_refresh_token_hours
    assert abs(_remaining(cookie) - hours * 3600) < 30


def test_unticked_refresh_slides_and_stays_session(client, soldier, monkeypatch):
    r = _login(client, soldier.personal_number, remember_me=False)
    cookie = r.cookies.get("refresh_token")
    first = decode_token(cookie)
    # Rotate 1 hour later: the new token gets a fresh full short lifetime.
    real_now = jwt_tokens._now
    monkeypatch.setattr(jwt_tokens, "_now", lambda: real_now() + timedelta(hours=1))
    rot = _refresh(client, cookie)
    assert rot.status_code == 200, rot.text
    assert _is_session(rot)
    new = decode_token(rot.cookies.get("refresh_token"))
    assert new["persist"] is False
    assert new["sid"] == first["sid"]
    assert new["jti"] != first["jti"]
    assert new["exp"] >= first["exp"] + 3600 - 2


def test_remembered_refresh_keeps_90_day_max_age(client, soldier):
    r = _login(client, soldier.personal_number, remember_me=True)
    rot = _refresh(client, r.cookies.get("refresh_token"))
    assert rot.status_code == 200
    assert f"max-age={90 * _DAY}" in _set_cookie(rot)
    assert abs(_remaining(rot.cookies.get("refresh_token")) - 90 * _DAY) < 30


def test_idle_unticked_token_is_rejected_after_its_short_lifetime(client, soldier, monkeypatch):
    real_now = jwt_tokens._now
    monkeypatch.setattr(jwt_tokens, "_now", lambda: real_now() - timedelta(hours=13))
    old = issue_refresh_token(user_id=soldier.id, token_version=soldier.token_version, persist=False)
    monkeypatch.setattr(jwt_tokens, "_now", real_now)
    assert _refresh(client, old).status_code == 401


def test_issue_refresh_token_lifetimes():
    s = get_settings()
    p = decode_token(issue_refresh_token(user_id=uuid.uuid4(), persist=True))
    n = decode_token(issue_refresh_token(user_id=uuid.uuid4(), persist=False))
    now = int(datetime.now(tz=UTC).timestamp())
    assert abs(p["exp"] - now - s.refresh_token_days * _DAY) < 30
    assert abs(n["exp"] - now - s.session_refresh_token_hours * 3600) < 30


def test_revocation_ttls_cover_both_lifetimes():
    max_life = get_settings().refresh_token_days * _DAY
    for persist in (True, False):
        payload = decode_token(issue_refresh_token(user_id=uuid.uuid4(), persist=persist))
        refresh_revocation.revoke(payload)
        r = get_redis()
        sid_ttl = r.ttl(f"auth:refresh:revoked:sid:{payload['sid']}")
        jti_ttl = r.ttl(f"auth:refresh:revoked:jti:{payload['jti']}")
        # sid outlives the longest token of any family; jti matches the token itself.
        assert sid_ttl >= max_life
        remaining = payload["exp"] - int(time.time())
        assert remaining - 5 <= jti_ttl <= remaining + 1


def test_sid_ttl_covers_session_hours_even_if_configured_longer_than_days(monkeypatch):
    odd = get_settings().model_copy(
        update={"refresh_token_days": 1, "session_refresh_token_hours": 100}
    )
    monkeypatch.setattr(jwt_tokens, "get_settings", lambda: odd)
    monkeypatch.setattr(refresh_revocation, "get_settings", lambda: odd)
    payload = decode_token(issue_refresh_token(user_id=uuid.uuid4(), persist=False))
    refresh_revocation.revoke(payload)
    assert get_redis().ttl(f"auth:refresh:revoked:sid:{payload['sid']}") >= 100 * 3600


# --- OIDC ---------------------------------------------------------------------------


@pytest.fixture
def provider(client):
    from app.services.oidc import OidcClient
    from tests.integration.test_oidc_login_routes import oidc_dep
    from tests.support.mock_oidc import MockOidcProvider
    from tests.unit.test_oidc_service import make_config

    mock = MockOidcProvider()
    oidc_client = OidcClient(make_config(), transport=mock.transport())
    client.app.dependency_overrides[oidc_dep()] = lambda: oidc_client
    yield mock
    client.app.dependency_overrides.pop(oidc_dep(), None)


def _linked(admin_session, pn):
    from tests.integration.test_oidc_login_routes import add_soldier, link

    s = add_soldier(admin_session, pn, f"{pn}@corp.example", role="commander")
    link(admin_session, s)
    return s


def _start(client, query: str = ""):
    client.cookies.clear()
    started = client.get(f"/api/auth/oidc/start{query}", follow_redirects=False)
    assert started.status_code == 302, started.text
    return started


def _callback(client, provider, started, extra_query: str = "", cookie_override: str | None = None):
    parts = urlsplit(provider.authorize(started.headers["location"], None))
    url = f"{parts.path}?{parts.query}{extra_query}"
    if cookie_override is not None:
        client.cookies.clear()
        client.cookies.set("oidc_txn", cookie_override, path="/api/auth/oidc")
    return client.get(url, follow_redirects=False)


def test_sso_default_is_remembered(client, admin_session, provider):
    _linked(admin_session, "6300001")
    resp = _callback(client, provider, _start(client))
    assert resp.status_code == 303
    assert f"max-age={90 * _DAY}" in _set_cookie(resp)
    cookie = resp.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is True
    rot = _refresh(client, cookie)
    assert f"max-age={90 * _DAY}" in _set_cookie(rot)


def test_sso_remember_zero_is_session_with_short_exp(client, admin_session, provider):
    _linked(admin_session, "6300002")
    resp = _callback(client, provider, _start(client, "?remember=0"))
    assert resp.status_code == 303
    assert _is_session(resp)
    cookie = resp.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is False
    assert abs(_remaining(cookie) - 12 * 3600) < 30
    assert _is_session(_refresh(client, cookie))


def test_sso_remember_one_is_remembered(client, admin_session, provider):
    _linked(admin_session, "6300003")
    resp = _callback(client, provider, _start(client, "?remember=1"))
    assert decode_token(resp.cookies.get("refresh_token"))["persist"] is True


def test_sso_forged_remember_on_callback_query_is_ignored(client, admin_session, provider):
    _linked(admin_session, "6300004")
    resp = _callback(client, provider, _start(client, "?remember=0"), extra_query="&remember=1")
    assert _is_session(resp)
    assert decode_token(resp.cookies.get("refresh_token"))["persist"] is False
    resp = _callback(client, provider, _start(client), extra_query="&remember=0")
    assert decode_token(resp.cookies.get("refresh_token"))["persist"] is True


def test_sso_tampering_with_transaction_cookie_cannot_flip_choice(client, admin_session, provider):
    _linked(admin_session, "6300005")
    started = _start(client, "?remember=0")
    token = started.cookies.get("oidc_txn")
    assert token
    forged = "r1." + token.split(".", 1)[-1]
    resp = _callback(client, provider, started, cookie_override=forged)
    # The binding hash no longer matches: login is denied, nothing is issued.
    assert resp.headers["location"].endswith("/login?sso_error=1")
    assert "refresh_token" not in resp.headers.get("set-cookie", "")


# --- SSO registration (first-time users) ----------------------------------------------


@pytest.fixture
def reg_world(admin_session):
    from tests.helpers import create_node
    from tests.integration.test_registration_routes import _setup_holding

    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name="sso-unit-rm", parent=holding)
    admin_session.commit()
    return node


def _sso_register(client, provider, node, query: str = "", cookie_override: str | None = None):
    from tests.integration.test_oidc_registration import STRANGER, register

    started = _start(client, query)
    parts = urlsplit(provider.authorize(started.headers["location"], STRANGER))
    cb = client.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    assert cb.headers["location"].endswith("/register?sso=1"), cb.headers["location"]
    if cookie_override is not None:
        client.cookies.set("oidc_reg", cookie_override, path="/api/auth")
    r = register(client, node)
    client.cookies.clear()
    return r


def test_sso_registration_unticked_is_session_with_short_exp(client, provider, reg_world):
    r = _sso_register(client, provider, reg_world, "?remember=0")
    assert r.status_code == 200, r.text
    assert _is_session(r)
    cookie = r.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is False
    assert abs(_remaining(cookie) - 12 * 3600) < 30
    assert _is_session(_refresh(client, cookie))


def test_sso_registration_default_is_remembered(client, provider, reg_world):
    r = _sso_register(client, provider, reg_world)
    assert r.status_code == 200, r.text
    assert f"max-age={90 * _DAY}" in _set_cookie(r)
    cookie = r.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is True
    assert abs(_remaining(cookie) - 90 * _DAY) < 30


def test_sso_registration_tampered_cookie_is_rejected_not_flipped(client, provider, reg_world):
    from tests.integration.test_oidc_registration import STRANGER, register

    started = _start(client, "?remember=0")
    parts = urlsplit(provider.authorize(started.headers["location"], STRANGER))
    cb = client.get(f"{parts.path}?{parts.query}", follow_redirects=False)
    token = cb.cookies.get("oidc_reg")
    assert token and token.startswith("r0.")
    client.cookies.set("oidc_reg", "r1." + token[3:], path="/api/auth")
    r = register(client, reg_world)
    assert r.status_code == 400
    assert "refresh_token" not in r.headers.get("set-cookie", "")


def test_invite_code_registration_stays_persistent(client, admin_session):
    from app.services.invite_codes import create_invite_code
    from tests.helpers import create_node
    from tests.integration.test_registration_routes import (
        _payload,
        _post_register,
        _setup_holding,
        _uid,
    )

    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()
    client.cookies.clear()
    r = _post_register(client, _payload(invite.code, node.id))
    assert f"max-age={90 * _DAY}" in _set_cookie(r)
    assert decode_token(r.cookies.get("refresh_token"))["persist"] is True
