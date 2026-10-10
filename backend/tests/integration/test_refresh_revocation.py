"""Per-session refresh-token revocation at logout.

Logout used to only delete the cookie client-side, so a refresh request that
was already in flight with the old cookie (and processed after logout) still
rotated it and re-set a valid cookie in the browser. Logout now records the
presented refresh token's ``jti`` and session family ``sid`` in Redis and
``/auth/refresh`` rejects either one with ``token_revoked``.
"""
from __future__ import annotations

import json
import time
import uuid

import pytest
import redis
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy.orm import Session

from app.auth import refresh_revocation
from app.auth.jwt_tokens import decode_token, issue_access_token, issue_refresh_token
from app.redis_client import get_redis
from app.settings import get_settings
from tests.helpers import create_soldier

_PASSWORD = "password-1234"


def _login(client: TestClient, personal_number: str) -> tuple[str, str]:
    """Return (access_token, refresh_cookie) for a fresh password login."""
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"personal_number": personal_number, "password": _PASSWORD})
    assert r.status_code == 200, r.text
    cookie = r.cookies.get("refresh_token")
    assert cookie
    client.cookies.clear()
    return r.json()["access_token"], cookie


def _refresh(client: TestClient, cookie: str | None):
    client.cookies.clear()
    headers = {"Cookie": f"refresh_token={cookie}"} if cookie is not None else {}
    r = client.post("/api/auth/refresh", headers=headers)
    client.cookies.clear()
    return r


def _logout(client: TestClient, access: str, cookie: str | None):
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {access}"}
    if cookie is not None:
        headers["Cookie"] = f"refresh_token={cookie}"
    r = client.post("/api/auth/logout", headers=headers)
    client.cookies.clear()
    return r


def _assert_cookie_deleted(response) -> None:
    set_cookie = response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()
    assert "Path=/api/auth" in set_cookie


@pytest.fixture
def soldier(admin_session: Session):
    s = create_soldier(admin_session, personal_number="7810001", password=_PASSWORD)
    admin_session.commit()
    return s


def test_refresh_tokens_carry_unique_jti_and_session_id():
    user_id = uuid.uuid4()
    a = decode_token(issue_refresh_token(user_id=user_id))
    b = decode_token(issue_refresh_token(user_id=user_id))
    assert a["jti"] != b["jti"]
    assert len(a["jti"]) == 32 and int(a["jti"], 16) >= 0
    assert a["sid"] != b["sid"]
    inherited = decode_token(issue_refresh_token(user_id=user_id, session_id=a["sid"]))
    assert inherited["sid"] == a["sid"] and inherited["jti"] != a["jti"]


def test_refresh_rotation_issues_new_jti_and_keeps_session_id(client, soldier):
    _, cookie = _login(client, soldier.personal_number)
    first = decode_token(cookie)
    seen = {first["jti"]}
    current = cookie
    for _ in range(3):
        r = _refresh(client, current)
        assert r.status_code == 200
        current = r.cookies.get("refresh_token")
        payload = decode_token(current)
        assert payload["jti"] not in seen
        assert payload["sid"] == first["sid"]
        seen.add(payload["jti"])


def test_logout_then_refresh_with_same_cookie_is_revoked(client, soldier):
    access, cookie = _login(client, soldier.personal_number)
    r = _logout(client, access, cookie)
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    _assert_cookie_deleted(r)

    r = _refresh(client, cookie)
    assert r.status_code == 401
    assert r.json()["detail"] == "token_revoked"


def test_logout_revokes_tokens_rotated_from_the_same_session(client, soldier):
    """A refresh processed just *before* logout rotated C1 -> C2; its response can
    still land in the browser after logout's cookie deletion. C2 shares C1's sid,
    so it is rejected too."""
    access, c1 = _login(client, soldier.personal_number)
    r = _refresh(client, c1)
    assert r.status_code == 200
    c2 = r.cookies.get("refresh_token")

    assert _logout(client, access, c1).status_code == 200

    r = _refresh(client, c2)
    assert r.status_code == 401
    assert r.json()["detail"] == "token_revoked"


def test_logout_is_per_device(client, soldier, admin_session):
    access_a, cookie_a = _login(client, soldier.personal_number)
    _, cookie_b = _login(client, soldier.personal_number)
    before_tv = soldier.token_version

    assert _logout(client, access_a, cookie_a).status_code == 200

    assert _refresh(client, cookie_a).status_code == 401
    r = _refresh(client, cookie_b)
    assert r.status_code == 200
    admin_session.refresh(soldier)
    assert soldier.token_version == before_tv


def test_legacy_token_without_jti_still_refreshes(client, soldier):
    settings = get_settings()
    legacy = jose_jwt.encode(
        {
            "sub": str(soldier.id),
            "type": "refresh",
            "tv": soldier.token_version,
            "exp": int(time.time()) + 3600,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    r = _refresh(client, legacy)
    assert r.status_code == 200
    rotated = decode_token(r.cookies.get("refresh_token"))
    assert rotated["jti"] and rotated["sid"]


def test_logout_with_legacy_cookie_still_ok(client, soldier):
    settings = get_settings()
    legacy = jose_jwt.encode(
        {"sub": str(soldier.id), "type": "refresh", "tv": soldier.token_version, "exp": int(time.time()) + 3600},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    r = _logout(client, access, legacy)
    assert r.status_code == 200
    _assert_cookie_deleted(r)
    assert get_redis().keys("auth:refresh:revoked:*") == []


@pytest.mark.parametrize("cookie", [None, "garbage.token.value"])
def test_logout_without_valid_cookie_is_ok_and_deletes_cookie(client, soldier, cookie):
    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    r = _logout(client, access, cookie)
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    _assert_cookie_deleted(r)
    assert get_redis().keys("auth:refresh:revoked:*") == []


def test_logout_with_access_token_as_cookie_revokes_nothing(client, soldier):
    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    r = _logout(client, access, access)
    assert r.status_code == 200
    assert get_redis().keys("auth:refresh:revoked:*") == []


def test_logout_still_requires_access_token(client, soldier):
    _, cookie = _login(client, soldier.personal_number)
    client.cookies.clear()
    r = client.post("/api/auth/logout", headers={"Cookie": f"refresh_token={cookie}"})
    assert r.status_code == 401
    assert _refresh(client, cookie).status_code == 200


def test_revoked_key_ttls_match_token_lifetime(client, soldier):
    days = get_settings().refresh_token_days
    access, cookie = _login(client, soldier.personal_number)
    payload = decode_token(cookie)
    assert _logout(client, access, cookie).status_code == 200

    r = get_redis()
    jti_ttl = r.ttl(f"auth:refresh:revoked:jti:{payload['jti']}")
    sid_ttl = r.ttl(f"auth:refresh:revoked:sid:{payload['sid']}")
    remaining = payload["exp"] - int(time.time())
    assert remaining - 5 <= jti_ttl <= remaining + 1
    assert jti_ttl <= days * 86400
    # The session family outlives any token rotated from it right before logout.
    assert days * 86400 <= sid_ttl <= days * 86400 + refresh_revocation.SESSION_TTL_MARGIN_SECONDS
    assert len(r.keys("auth:refresh:revoked:*")) == 2


def test_short_lived_token_gets_short_jti_ttl():
    token = issue_refresh_token(user_id=uuid.uuid4(), lifetime_seconds=120)
    payload = decode_token(token)
    refresh_revocation.revoke(payload)
    ttl = get_redis().ttl(f"auth:refresh:revoked:jti:{payload['jti']}")
    assert 100 <= ttl <= 120
    assert refresh_revocation.is_revoked(payload) is True


class _BrokenRedis:
    def __getattr__(self, name):
        def _fail(*args, **kwargs):
            raise redis.ConnectionError("redis down")

        return _fail


def test_refresh_fails_open_when_store_unavailable(client, soldier, monkeypatch, caplog):
    access, cookie = _login(client, soldier.personal_number)
    assert _logout(client, access, cookie).status_code == 200

    monkeypatch.setattr(refresh_revocation, "get_redis", lambda: _BrokenRedis())
    with caplog.at_level("WARNING", logger="app.auth"):
        r = _refresh(client, cookie)
    # Fail open: no worse than before revocation existed.
    assert r.status_code == 200
    assert any("revocation" in rec.message.lower() for rec in caplog.records)


def test_logout_succeeds_when_store_unavailable(client, soldier, monkeypatch, caplog):
    access, cookie = _login(client, soldier.personal_number)
    monkeypatch.setattr(refresh_revocation, "get_redis", lambda: _BrokenRedis())
    with caplog.at_level("WARNING", logger="app.auth"):
        r = _logout(client, access, cookie)
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    _assert_cookie_deleted(r)
    assert any("revocation" in rec.message.lower() for rec in caplog.records)


# --- login revokes the refresh cookie the browser presented -----------------------
# Race being closed: a restore refresh for user A's cookie C1 is processed before
# user B's login but answered after it, so the browser's last Set-Cookie is A's
# rotated C2 and B's next refresh would silently run as A. Login now revokes the
# presented C1's session (jti + sid), so C2 is dead and B is sent to /login instead.


def _login_presenting(client: TestClient, personal_number: str, cookie: str, password: str = _PASSWORD):
    client.cookies.clear()
    r = client.post(
        "/api/auth/login",
        json={"personal_number": personal_number, "password": password},
        headers={"Cookie": f"refresh_token={cookie}"},
    )
    client.cookies.clear()
    return r


@pytest.fixture
def other_soldier(admin_session: Session):
    s = create_soldier(admin_session, personal_number="7810002", password=_PASSWORD)
    admin_session.commit()
    return s


def test_login_revokes_presented_cookie_session(client, soldier, other_soldier):
    _, c1 = _login(client, soldier.personal_number)
    _, other_device = _login(client, soldier.personal_number)
    r = _refresh(client, c1)
    assert r.status_code == 200
    c2 = r.cookies.get("refresh_token")

    r = _login_presenting(client, other_soldier.personal_number, c1)
    assert r.status_code == 200
    b_cookie = r.cookies.get("refresh_token")

    r = _refresh(client, c2)
    assert r.status_code == 401
    assert r.json()["detail"] == "token_revoked"
    assert _refresh(client, b_cookie).status_code == 200
    # A's separate device session is untouched (per-session, no token_version bump).
    assert _refresh(client, other_device).status_code == 200


def test_failed_login_does_not_revoke_presented_cookie(client, soldier, other_soldier):
    _, c1 = _login(client, soldier.personal_number)
    r = _login_presenting(client, other_soldier.personal_number, c1, password="wrong-password")
    assert r.status_code == 401
    assert get_redis().keys("auth:refresh:revoked:*") == []
    assert _refresh(client, c1).status_code == 200


def test_login_with_garbage_cookie_is_ok_and_stores_nothing(client, soldier):
    r = _login_presenting(client, soldier.personal_number, "garbage.token.value")
    assert r.status_code == 200
    assert r.cookies.get("refresh_token")
    assert get_redis().keys("auth:refresh:revoked:*") == []


def test_login_succeeds_when_store_unavailable(client, soldier, other_soldier, monkeypatch, caplog):
    _, c1 = _login(client, soldier.personal_number)
    monkeypatch.setattr(refresh_revocation, "get_redis", lambda: _BrokenRedis())
    with caplog.at_level("WARNING", logger="app.auth"):
        r = _login_presenting(client, other_soldier.personal_number, c1)
    assert r.status_code == 200
    assert r.cookies.get("refresh_token")
    assert any("revocation" in rec.message.lower() for rec in caplog.records)


def test_register_revokes_presented_cookie_session(client, soldier, admin_session):
    from app.services.invite_codes import create_invite_code
    from tests.helpers import create_node
    from tests.integration.test_registration_routes import _payload, _setup_holding, _uid

    _, c1 = _login(client, soldier.personal_number)
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    client.cookies.clear()
    r = client.post(
        "/api/auth/register",
        data={"payload": json.dumps(_payload(invite.code, node.id))},
        headers={"Cookie": f"refresh_token={c1}"},
    )
    client.cookies.clear()
    assert r.status_code == 200, r.text
    assert _refresh(client, c1).status_code == 401
