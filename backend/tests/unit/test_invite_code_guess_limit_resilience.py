"""The invite-code guess limiter calls the limits backend directly; it must
fail open to the in-memory fallback on a Redis error instead of returning 500."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.settings import get_settings


def _request(ip: str) -> Request:
    return Request({"type": "http", "client": (ip, 1), "headers": [], "path": "/x"})


def _limit_count() -> int:
    return int(get_settings().invite_code_rate_limit.split("/")[0])


@pytest.fixture
def auth_routes():
    import app.routes.auth as auth_routes

    return auth_routes


def test_limit_triggers_at_threshold_with_healthy_storage(auth_routes):
    for _ in range(_limit_count()):
        auth_routes._enforce_invite_code_guess_limit(_request("8.8.1.1"))
    with pytest.raises(HTTPException) as exc:
        auth_routes._enforce_invite_code_guess_limit(_request("8.8.1.1"))
    assert exc.value.status_code == 429


def test_broken_storage_does_not_500_and_still_limits_in_process(auth_routes, monkeypatch):
    from app.rate_limit import build_limiter

    dead = build_limiter("redis://127.0.0.1:1/0")
    monkeypatch.setattr(auth_routes, "limiter", dead)
    for _ in range(_limit_count()):
        auth_routes._enforce_invite_code_guess_limit(_request("8.8.2.2"))  # no exception
    with pytest.raises(HTTPException) as exc:
        auth_routes._enforce_invite_code_guess_limit(_request("8.8.2.2"))
    assert exc.value.status_code == 429
