from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_soldier


def test_first_login_onboarding_sets_fields(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="onbrt-1")

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": "vegetarian", "food_constraints": None,
            "last_mitvahim_date": "2026-01-01", "last_alal_date": None,
            "exemption_requests": [], "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["food_type"] == "vegetarian"
    assert body["hr_onboarding_completed_at"] is not None


def test_first_login_onboarding_requires_password_changed(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="onbrt-2", must_change_password=True)

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": None, "food_constraints": None,
            "last_mitvahim_date": None, "last_alal_date": None,
            "exemption_requests": [], "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 403


def test_first_login_onboarding_rejects_bad_exemption(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="onbrt-3")

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": None, "food_constraints": None,
            "last_mitvahim_date": None, "last_alal_date": None,
            "exemption_requests": [{"exemption_type_id": "not-a-uuid"}],
            "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 400
