"""An unticked "remember me" login stays a session cookie across refresh rotations.

``/auth/refresh`` used to always set a persistent Max-Age, so one refresh turned a
browser-session login into a persistent one. The ``persist`` claim carries the
login's choice across rotations; tokens without the claim stay persistent.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt as jose_jwt
from sqlalchemy.orm import Session

from app.auth.jwt_tokens import decode_token
from app.settings import get_settings
from tests.helpers import create_soldier

_PASSWORD = "password-1234"
_MAX_AGE = get_settings().refresh_token_days * 24 * 3600


def _login(client, personal_number: str, **extra):
    client.cookies.clear()
    r = client.post(
        "/api/auth/login",
        json={"personal_number": personal_number, "password": _PASSWORD, **extra},
    )
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r


def _refresh(client, cookie: str):
    client.cookies.clear()
    r = client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={cookie}"})
    client.cookies.clear()
    assert r.status_code == 200, r.text
    return r


def _set_cookie(response) -> str:
    headers = [
        h for h in response.headers.get_list("set-cookie") if h.startswith("refresh_token=")
    ]
    assert len(headers) == 1
    return headers[0]


def _is_session_cookie(response) -> bool:
    header = _set_cookie(response).lower()
    return "max-age" not in header and "expires" not in header


def _has_max_age(response) -> bool:
    return f"max-age={_MAX_AGE}" in _set_cookie(response).lower()


@pytest.fixture
def soldier(admin_session: Session):
    s = create_soldier(admin_session, personal_number="7820001", password=_PASSWORD)
    admin_session.commit()
    return s


def test_session_login_stays_session_cookie_across_two_rotations(client, soldier):
    login = _login(client, soldier.personal_number, remember_me=False)
    assert _is_session_cookie(login)
    cookie = login.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is False

    for _ in range(2):
        r = _refresh(client, cookie)
        assert _is_session_cookie(r)
        cookie = r.cookies.get("refresh_token")
        assert decode_token(cookie)["persist"] is False


def test_remember_me_login_keeps_max_age_across_rotations(client, soldier):
    login = _login(client, soldier.personal_number, remember_me=True)
    assert _has_max_age(login)
    cookie = login.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is True

    for _ in range(2):
        r = _refresh(client, cookie)
        assert _has_max_age(r)
        cookie = r.cookies.get("refresh_token")
        assert decode_token(cookie)["persist"] is True


def test_token_without_persist_claim_is_treated_as_persistent(client, soldier):
    settings = get_settings()
    exp = datetime.now(tz=UTC) + timedelta(days=1)
    old = jose_jwt.encode(
        {
            "sub": str(soldier.id), "type": "refresh", "tv": soldier.token_version,
            "jti": uuid.uuid4().hex, "sid": uuid.uuid4().hex, "exp": int(exp.timestamp()),
        },
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    r = _refresh(client, old)
    assert _has_max_age(r)
    assert decode_token(r.cookies.get("refresh_token"))["persist"] is True


def test_register_cookie_stays_persistent_through_refresh(client, admin_session):
    from app.services.invite_codes import create_invite_code
    from tests.helpers import create_node
    from tests.integration.test_registration_routes import _payload, _setup_holding, _uid

    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()
    client.cookies.clear()
    r = client.post(
        "/api/auth/register", data={"payload": json.dumps(_payload(invite.code, node.id))}
    )
    client.cookies.clear()
    assert r.status_code == 200, r.text
    assert _has_max_age(r)
    cookie = r.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is True
    assert _has_max_age(_refresh(client, cookie))


def test_oidc_login_cookie_is_remembered_by_default_and_stays_so_through_refresh(
    client, admin_session
):
    from app.services.oidc import OidcClient
    from tests.integration.test_oidc_login_routes import add_soldier, link, oidc_dep, sso
    from tests.support.mock_oidc import MockOidcProvider
    from tests.unit.test_oidc_service import make_config

    mock = MockOidcProvider()
    oidc_client = OidcClient(make_config(), transport=mock.transport())
    client.app.dependency_overrides[oidc_dep()] = lambda: oidc_client
    try:
        s = add_soldier(admin_session, "6200001", "persist@corp.example", role="commander")
        link(admin_session, s)
        response = sso(client, mock)
    finally:
        client.app.dependency_overrides.pop(oidc_dep(), None)
    assert response.status_code == 303
    assert _has_max_age(response)
    cookie = response.cookies.get("refresh_token")
    assert decode_token(cookie)["persist"] is True
    assert _has_max_age(_refresh(client, cookie))
