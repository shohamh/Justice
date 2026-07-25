from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_update_theme_preference_persists(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7600023")

    r = client.patch(
        "/api/me/theme-preference",
        headers=auth_headers(s),
        json={"theme_preference": "dark"},
    )
    assert r.status_code == 200
    assert r.json() == {"theme_preference": "dark"}

    r2 = client.get("/api/me", headers=auth_headers(s))
    assert r2.json()["theme_preference"] == "dark"


def test_update_theme_preference_rejects_invalid_value(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7600024")

    r = client.patch(
        "/api/me/theme-preference",
        headers=auth_headers(s),
        json={"theme_preference": "purple"},
    )
    assert r.status_code == 422


def test_update_theme_preference_requires_auth(client: TestClient):
    r = client.patch("/api/me/theme-preference", json={"theme_preference": "dark"})
    assert r.status_code == 401
