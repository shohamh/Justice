from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import SoldierHrProfile
from tests.helpers import auth_headers, create_node, create_soldier


def _hr_linked_soldier(session, *, personal_number: str, hierarchy_node_id=None):
    soldier = create_soldier(session, personal_number=personal_number, hierarchy_node_id=hierarchy_node_id)
    session.add(SoldierHrProfile(personal_number=personal_number, raw_dto={}, soldier_id=soldier.id))
    session.commit()
    return soldier


def test_admin_can_generate_activation_code(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="hractrt-admin-1", role="admin")
    target = _hr_linked_soldier(admin_session, personal_number="hractrt-target-1")

    r = client.post(
        f"/api/soldiers/{target.id}/activation-code", headers=auth_headers(admin),
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["code"]) == 8
    assert "expires_at" in body


def test_plain_soldier_cannot_generate_activation_code(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="hractrt-soldier-1")
    target = _hr_linked_soldier(admin_session, personal_number="hractrt-target-2")

    r = client.post(
        f"/api/soldiers/{target.id}/activation-code", headers=auth_headers(soldier),
    )
    assert r.status_code == 403


def test_generate_for_soldier_with_no_hr_profile_returns_404(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="hractrt-admin-2", role="admin")
    target = create_soldier(admin_session, personal_number="hractrt-target-3")

    r = client.post(
        f"/api/soldiers/{target.id}/activation-code", headers=auth_headers(admin),
    )
    assert r.status_code == 404
