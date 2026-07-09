from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.requests import Request

from tests.helpers import create_soldier


def test_login_account_key_extracts_personal_number():
    from app.routes.auth import _login_account_key

    scope = {"type": "http", "client": ("1.2.3.4", 1234), "headers": []}
    request = Request(scope)
    request._body = json.dumps({"personal_number": "1234567", "password": "x"}).encode()

    assert _login_account_key(request) == "login-account:1234567"


def test_login_account_key_falls_back_to_ip_on_bad_body():
    from app.routes.auth import _login_account_key

    scope = {"type": "http", "client": ("1.2.3.4", 1234), "headers": []}
    request = Request(scope)
    request._body = b"not json"

    assert _login_account_key(request) == "1.2.3.4"


def test_repeated_failed_logins_for_one_account_get_rate_limited(
    client: TestClient, admin_session: Session, monkeypatch
):
    from app.settings import get_settings
    from app.rate_limit import limiter

    monkeypatch.setenv("LOGIN_ACCOUNT_RATE_LIMIT", "2/minute")
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "1000/minute")
    get_settings.cache_clear()
    limiter.reset()
    try:
        create_soldier(admin_session, personal_number="7900001", password="password-1234")

        for _ in range(2):
            r = client.post(
                "/api/auth/login",
                json={"personal_number": "7900001", "password": "wrong"},
            )
            assert r.status_code == 401

        r = client.post(
            "/api/auth/login",
            json={"personal_number": "7900001", "password": "wrong"},
        )
        assert r.status_code == 429
    finally:
        get_settings.cache_clear()
        limiter.reset()


def test_rate_limit_on_one_account_does_not_block_another(
    client: TestClient, admin_session: Session, monkeypatch
):
    from app.settings import get_settings
    from app.rate_limit import limiter

    monkeypatch.setenv("LOGIN_ACCOUNT_RATE_LIMIT", "1/minute")
    monkeypatch.setenv("LOGIN_RATE_LIMIT", "1000/minute")
    get_settings.cache_clear()
    limiter.reset()
    try:
        create_soldier(admin_session, personal_number="7900002", password="password-1234")
        create_soldier(admin_session, personal_number="7900003", password="password-1234")

        r1 = client.post("/api/auth/login", json={"personal_number": "7900002", "password": "wrong"})
        assert r1.status_code == 401
        r2 = client.post("/api/auth/login", json={"personal_number": "7900002", "password": "wrong"})
        assert r2.status_code == 429

        # A different account, same client/IP, is unaffected.
        r3 = client.post("/api/auth/login", json={"personal_number": "7900003", "password": "wrong"})
        assert r3.status_code == 401
    finally:
        get_settings.cache_clear()
        limiter.reset()
