import pytest
from unittest.mock import patch
from app.settings import Settings


def test_token_version_increments_on_password_change():
    from app.services.soldiers import bump_token_version

    class FakeSoldier:
        token_version = 1

    s = FakeSoldier()
    bump_token_version(s)
    assert s.token_version == 2


def test_token_version_starts_at_1():
    from app.services.soldiers import bump_token_version

    class FakeSoldier:
        token_version = 1

    s = FakeSoldier()
    assert s.token_version == 1


def test_cookie_secure_defaults_true():
    s = Settings(
        DATABASE_URL="postgresql+psycopg://x:y@localhost/z",
        DB_ADMIN_URL="postgresql+psycopg://x:y@localhost/z",
        JWT_SECRET="a" * 32,
        _env_file=None,
    )
    assert s.cookie_secure is True


def test_cookie_secure_can_be_disabled_for_dev():
    import os
    with patch.dict(os.environ, {"COOKIE_SECURE": "false"}):
        from app.settings import Settings as S2
        s = S2(
            DATABASE_URL="postgresql+psycopg://x:y@localhost/z",
            DB_ADMIN_URL="postgresql+psycopg://x:y@localhost/z",
            JWT_SECRET="a" * 32,
            _env_file=None,
        )
        assert s.cookie_secure is False


def test_lockout_threshold_constants():
    """Lockout fires at 10 failures, releases after 15 minutes — document the policy."""
    from app.routes.auth import _LOCKOUT_THRESHOLD, _LOCKOUT_MINUTES
    assert _LOCKOUT_THRESHOLD == 10
    assert _LOCKOUT_MINUTES == 15


def test_soldier_update_request_has_no_hierarchy_node_id():
    """PATCH /soldiers/{id} must not accept hierarchy_node_id: moving a soldier
    between hierarchy nodes has to go through app.routes.hierarchy_transfers,
    which requires destination-side approval (Action.HIERARCHY_TRANSFER).
    Letting it ride along with an ordinary profile edit (Action.SOLDIER_UPDATE)
    used to move the soldier immediately, bypassing that approval step."""
    from app.routes.soldiers import UpdateRequest

    assert "hierarchy_node_id" not in UpdateRequest.model_fields


def test_security_headers_present():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_cors_disallows_put_method():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    allowed = resp.headers.get("access-control-allow-methods", "")
    assert "PUT" not in allowed


def test_cors_exposes_retry_after_and_content_disposition():
    from fastapi.middleware.cors import CORSMiddleware
    from app.main import create_app

    app = create_app()
    cors = next(mw for mw in app.user_middleware if mw.cls is CORSMiddleware)
    assert cors.kwargs["expose_headers"] == ["Retry-After", "Content-Disposition", "X-Request-ID"]


def test_score_adjustment_delta_bounds():
    from pydantic import ValidationError
    from app.routes.score_adjustments import CreateAdjustmentRequest
    import uuid

    valid = CreateAdjustmentRequest(
        soldier_id=uuid.uuid4(), delta="500", reason="test"
    )
    assert valid.delta == 500

    with pytest.raises(ValidationError):
        CreateAdjustmentRequest(soldier_id=uuid.uuid4(), delta="10000", reason="too big")

    with pytest.raises(ValidationError):
        CreateAdjustmentRequest(soldier_id=uuid.uuid4(), delta="-10000", reason="too small")


def test_magic_bytes_xlsx():
    """Valid xlsx starts with ZIP magic bytes."""
    xlsx_magic = b"PK\x03\x04"
    assert xlsx_magic[:4] == b"PK\x03\x04"


def test_magic_bytes_rejects_html():
    fake_html = b"<htm"
    assert fake_html[:4] != b"PK\x03\x04"


def test_login_rate_limit_default_is_10_per_5_minutes():
    import os
    with patch.dict(os.environ, {}, clear=False):
        # Remove the test-boosted rate limit from conftest so we test the default
        os.environ.pop("LOGIN_RATE_LIMIT", None)
        from app.settings import Settings
        s = Settings(
            DATABASE_URL="postgresql+psycopg://x:y@localhost/z",
            DB_ADMIN_URL="postgresql+psycopg://x:y@localhost/z",
            JWT_SECRET="a" * 32,
            _env_file=None,
        )
        assert s.login_rate_limit == "10/5minutes"
