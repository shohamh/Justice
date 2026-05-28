from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_me_returns_current_user(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6000001", role="admin")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert body["personal_number"] == "6000001"
    assert body["role"] == "admin"
    assert body["must_change_password"] is False


def test_change_password_clears_flag(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6000002", password="old-password-123",
                       must_change_password=True)
    r = client.post("/api/auth/change-password", headers=auth_headers(s),
                    json={"current_password": "old-password-123", "new_password": "brand-new-password"})
    assert r.status_code == 200
    admin_session.expire_all()
    refreshed = admin_session.get(type(s), s.id)
    assert refreshed.must_change_password is False


def test_change_password_rejects_wrong_current(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6000003", password="old-password-123")
    r = client.post("/api/auth/change-password", headers=auth_headers(s),
                    json={"current_password": "wrong", "new_password": "brand-new-password"})
    assert r.status_code == 400


def test_change_password_enforces_min_length(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6000004", password="old-password-123")
    r = client.post("/api/auth/change-password", headers=auth_headers(s),
                    json={"current_password": "old-password-123", "new_password": "short"})
    assert r.status_code == 422 or r.status_code == 400
