from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.password import hash_password
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
    assert r.json()["detail"] == "invalid_credentials"


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
