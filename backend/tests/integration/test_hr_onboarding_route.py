from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType, SoldierHrProfile
from tests.helpers import auth_headers, create_soldier


def _eligible_soldier(session, *, personal_number: str, **kwargs):
    # must_change_password=False: this route is gated by require_password_changed,
    # so a realistic caller here already completed the activation-code login
    # and change-password steps (C1) — HR-linked and not yet onboarded is what
    # makes them eligible for first-login-onboarding itself (C3).
    soldier = create_soldier(session, personal_number=personal_number, must_change_password=False, **kwargs)
    session.add(SoldierHrProfile(personal_number=personal_number, raw_dto={}, soldier_id=soldier.id))
    session.commit()
    return soldier


def test_first_login_onboarding_sets_fields(client: TestClient, admin_session: Session):
    soldier = _eligible_soldier(admin_session, personal_number="onbrt-1")

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
    soldier = _eligible_soldier(admin_session, personal_number="onbrt-3")

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


def test_first_login_onboarding_rejects_soldier_not_hr_linked(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="onbrt-4")  # not HR-linked

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": None, "food_constraints": None,
            "last_mitvahim_date": None, "last_alal_date": None,
            "exemption_requests": [], "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "not_eligible"


def test_first_login_onboarding_rejects_already_onboarded_soldier(client: TestClient, admin_session: Session):
    from datetime import datetime, timezone

    soldier = _eligible_soldier(admin_session, personal_number="onbrt-5")
    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    admin_session.commit()

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": None, "food_constraints": None,
            "last_mitvahim_date": None, "last_alal_date": None,
            "exemption_requests": [], "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "not_eligible"


def test_first_login_onboarding_rejects_invalid_food_type(client: TestClient, admin_session: Session):
    soldier = _eligible_soldier(admin_session, personal_number="onbrt-6")

    r = client.post(
        "/api/auth/first-login-onboarding",
        json={
            "food_type": "not_a_real_type", "food_constraints": None,
            "last_mitvahim_date": None, "last_alal_date": None,
            "exemption_requests": [], "personal_constraints": [],
        },
        headers=auth_headers(soldier),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_food_type"
