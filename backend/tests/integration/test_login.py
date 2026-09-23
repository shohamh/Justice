from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password, verify_password
from app.db.models import Soldier


def _create_soldier(
    session: Session, personal_number: str, password: str, role: str = "soldier"
) -> Soldier:
    s = Soldier(
        personal_number=personal_number,
        full_name=f"Test {personal_number}",
        password_hash=hash_password(password),
        role=role,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def test_login_with_correct_credentials_returns_tokens(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "9000001", "hunter2-test")
    r = client.post(
        "/api/auth/login", json={"personal_number": "9000001", "password": "hunter2-test"}
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    # refresh token comes back as a cookie
    cookies = r.cookies
    assert "refresh_token" in cookies


def test_login_with_wrong_password_returns_401(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "9000002", "right-password")
    r = client.post("/api/auth/login", json={"personal_number": "9000002", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"]["detail"] == "invalid_credentials"


def test_login_401_reports_attempt_count(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "7960001", "Correct123Pass")
    r = client.post("/api/auth/login", json={"personal_number": "7960001", "password": "wrong"})
    assert r.status_code == 401
    body = r.json()["detail"]
    assert body["attempts"] == 1
    assert body["max_attempts"] == 10


def test_login_locks_account_on_threshold_attempt(client: TestClient, admin_session: Session):
    from app.routes.auth import _LOCKOUT_MINUTES, _LOCKOUT_THRESHOLD

    _create_soldier(admin_session, "7960002", "Correct123Pass")

    for attempt in range(1, _LOCKOUT_THRESHOLD):
        r = client.post(
            "/api/auth/login", json={"personal_number": "7960002", "password": "wrong"}
        )
        assert r.status_code == 401, f"attempt {attempt} should still be 401"
        body = r.json()["detail"]
        assert body["attempts"] == attempt
        assert body["max_attempts"] == _LOCKOUT_THRESHOLD

    # The attempt that reaches the threshold locks the account immediately —
    # this request itself gets 429, not the one after it.
    r = client.post("/api/auth/login", json={"personal_number": "7960002", "password": "wrong"})
    assert r.status_code == 429
    assert r.json()["detail"] == "account_locked"
    assert r.headers["Retry-After"] == str(_LOCKOUT_MINUTES * 60)


def test_login_with_unknown_user_returns_401(client: TestClient):
    r = client.post("/api/auth/login", json={"personal_number": "9999999", "password": "anything"})
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_credentials"


def test_login_writes_audit_row_on_success(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "9000003", "audit-test")
    r = client.post(
        "/api/auth/login", json={"personal_number": "9000003", "password": "audit-test"}
    )
    assert r.status_code == 200
    from sqlalchemy import text

    rows = admin_session.execute(
        text(
            "SELECT action FROM audit_log WHERE action='auth.login.success' ORDER BY created_at DESC LIMIT 1"
        )
    ).all()
    assert len(rows) == 1


def test_login_writes_audit_row_on_failure(client: TestClient, admin_session: Session):
    _create_soldier(admin_session, "9000004", "audit-test")
    client.post("/api/auth/login", json={"personal_number": "9000004", "password": "wrong"})
    from sqlalchemy import text

    rows = admin_session.execute(
        text(
            "SELECT action FROM audit_log WHERE action='auth.login.failure' ORDER BY created_at DESC LIMIT 1"
        )
    ).all()
    assert len(rows) == 1


import logging


def test_warns_when_secure_cookie_set_over_plain_http(client, admin_session, caplog, monkeypatch):
    from app.settings import get_settings
    from tests.helpers import create_soldier

    get_settings.cache_clear()
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        s = create_soldier(admin_session, personal_number="7700001", password="password-1234")
        with caplog.at_level(logging.WARNING, logger="app.auth"):
            r = client.post(
                "/api/auth/login",
                json={"personal_number": "7700001", "password": "password-1234"},
                headers={"X-Forwarded-Proto": "http"},
            )
        assert r.status_code == 200
        assert any("cookie_secure" in rec.message.lower() for rec in caplog.records)
    finally:
        monkeypatch.delenv("COOKIE_SECURE", raising=False)
        get_settings.cache_clear()


from datetime import datetime, timedelta, timezone

from app.db.models import SoldierActivationCode, SoldierHrProfile


def _hr_linked_soldier_with_code(session, *, personal_number: str, code: str = "ACTV1234"):
    from app.auth.password import hash_password

    soldier = Soldier(
        personal_number=personal_number,
        full_name=f"Test {personal_number}",
        password_hash=hash_password("placeholder-nobody-knows-this"),
        must_change_password=True,
    )
    session.add(soldier)
    session.flush()
    session.add(SoldierHrProfile(personal_number=personal_number, raw_dto={}, soldier_id=soldier.id))
    session.add(SoldierActivationCode(
        soldier_id=soldier.id, code=code,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=7),
    ))
    session.commit()
    session.refresh(soldier)
    return soldier


def test_login_with_valid_activation_code_succeeds(client: TestClient, admin_session: Session):
    soldier = _hr_linked_soldier_with_code(admin_session, personal_number="8100001")

    r = client.post(
        "/api/auth/login", json={"personal_number": "8100001", "password": "ACTV1234"}
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["must_change_password"] is True


def test_activation_code_becomes_temporary_password_until_changed(client: TestClient, admin_session: Session):
    """The SoldierActivationCode row itself is single-use (used_at gets set
    on first use). Logging in again with the same string right afterward
    still succeeds — but as an ordinary password login, not a fresh
    activation, because (C1) the code became the soldier's real
    password_hash on first use. That window is short-lived though: once the
    soldier actually changes their password via /auth/change-password, the
    original code stops being a valid credential at all — proving the
    code-as-temporary-password state doesn't linger past the change."""
    soldier = _hr_linked_soldier_with_code(admin_session, personal_number="8100002")

    first = client.post(
        "/api/auth/login", json={"personal_number": "8100002", "password": "ACTV1234"}
    )
    assert first.status_code == 200

    code = admin_session.execute(
        select(SoldierActivationCode).where(SoldierActivationCode.soldier_id == soldier.id)
    ).scalar_one()
    assert code.used_at is not None

    # Still works as an ordinary password login — the code is now password_hash.
    second = client.post(
        "/api/auth/login", json={"personal_number": "8100002", "password": "ACTV1234"}
    )
    assert second.status_code == 200
    access_token = second.json()["access_token"]

    change_resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "ACTV1234", "new_password": "Br4nd-New!Pass"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert change_resp.status_code == 200

    # Now that a real password has superseded it, the original code must no
    # longer work as a credential at all.
    third = client.post(
        "/api/auth/login", json={"personal_number": "8100002", "password": "ACTV1234"}
    )
    assert third.status_code == 401


def test_login_with_expired_activation_code_fails(client: TestClient, admin_session: Session):
    soldier = _hr_linked_soldier_with_code(admin_session, personal_number="8100003")
    code = admin_session.execute(
        select(SoldierActivationCode).where(SoldierActivationCode.soldier_id == soldier.id)
    ).scalar_one()
    code.expires_at = datetime.now(tz=timezone.utc) - timedelta(days=1)
    admin_session.commit()

    r = client.post(
        "/api/auth/login", json={"personal_number": "8100003", "password": "ACTV1234"}
    )
    assert r.status_code == 401


def test_login_with_wrong_activation_code_fails_normally(client: TestClient, admin_session: Session):
    _hr_linked_soldier_with_code(admin_session, personal_number="8100004")

    r = client.post(
        "/api/auth/login", json={"personal_number": "8100004", "password": "WRONGCOD"}
    )
    assert r.status_code == 401
    assert r.json()["detail"]["detail"] == "invalid_credentials"


def test_activation_code_login_then_change_password_then_protected_route_succeeds(
    client: TestClient, admin_session: Session
):
    """C1 end-to-end: activation-code login is no longer a dead end. The code
    becomes the soldier's real current_password, so change-password succeeds
    with it, and a protected route (gated by require_password_changed) is
    reachable right afterward."""
    _hr_linked_soldier_with_code(admin_session, personal_number="8100005", code="ACTV5678")

    login_resp = client.post(
        "/api/auth/login", json={"personal_number": "8100005", "password": "ACTV5678"}
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["must_change_password"] is True
    access_token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # The activation code itself must now verify as current_password.
    change_resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "ACTV5678", "new_password": "Br4nd-New!Pass"},
        headers=headers,
    )
    assert change_resp.status_code == 200

    protected_resp = client.get(
        "/api/calendar/holidays", params={"year": 2026}, headers=headers,
    )
    assert protected_resp.status_code == 200


def test_activation_code_login_bumps_token_version_invalidating_old_sessions(
    client: TestClient, admin_session: Session,
):
    soldier = _hr_linked_soldier_with_code(admin_session, personal_number="8100006", code="ACTV9999")
    old_token_version = soldier.token_version

    r = client.post(
        "/api/auth/login", json={"personal_number": "8100006", "password": "ACTV9999"}
    )
    assert r.status_code == 200

    admin_session.refresh(soldier)
    assert soldier.token_version == old_token_version + 1
    # Positive check: the activation code itself now verifies as the
    # soldier's real password_hash (a `!=` comparison against a freshly
    # salted hash_password() call would be a tautology and prove nothing).
    assert verify_password("ACTV9999", soldier.password_hash)


def test_activation_code_login_writes_audit_context_marking_method(
    client: TestClient, admin_session: Session,
):
    from sqlalchemy import text

    _hr_linked_soldier_with_code(admin_session, personal_number="8100007", code="ACTV0007")

    r = client.post(
        "/api/auth/login", json={"personal_number": "8100007", "password": "ACTV0007"}
    )
    assert r.status_code == 200

    rows = admin_session.execute(
        text(
            "SELECT context FROM audit_log WHERE action='auth.login.success' "
            "ORDER BY created_at DESC LIMIT 1"
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].context.get("method") == "activation_code"
