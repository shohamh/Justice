from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_onboards_without_password_gets_temp(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000001", role="admin")
    d = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r = client.post(
        "/api/soldiers",
        headers=auth_headers(admin),
        json={"personal_number": "4100001", "full_name": "טוראי", "hierarchy_node_id": str(d.id)},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "soldier"
    assert body["must_change_password"] is True
    assert len(body["temp_password"]) >= 10


def test_onboard_with_password_no_temp_returned(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000002", role="admin")
    r = client.post(
        "/api/soldiers",
        headers=auth_headers(admin),
        json={
            "personal_number": "4100002",
            "full_name": "טוראי",
            "hierarchy_node_id": None,
            "password": "chosen-password-123",
        },
    )
    assert r.status_code == 201
    assert r.json()["temp_password"] is None


def test_duty_manager_can_only_onboard_in_scope(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(
        admin_session, personal_number="4000003", role="duty_manager", hierarchy_node_id=b.id
    )
    admin_session.commit()
    ok = client.post(
        "/api/soldiers",
        headers=auth_headers(dm),
        json={"personal_number": "4100003", "full_name": "x", "hierarchy_node_id": str(b.id)},
    )
    assert ok.status_code == 201
    denied = client.post(
        "/api/soldiers",
        headers=auth_headers(dm),
        json={"personal_number": "4100004", "full_name": "x", "hierarchy_node_id": str(other.id)},
    )
    assert denied.status_code == 403


def test_reset_password_returns_temp_and_sets_flag(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000005", role="admin")
    target = create_soldier(admin_session, personal_number="4100005")
    r = client.post(f"/api/soldiers/{target.id}/reset-password", headers=auth_headers(admin))
    assert r.status_code == 200
    assert len(r.json()["temp_password"]) >= 10


def test_only_admin_assigns_role(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000006", role="admin")
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    dm = create_soldier(
        admin_session, personal_number="4000007", role="duty_manager", hierarchy_node_id=b.id
    )
    target = create_soldier(admin_session, personal_number="4100006", hierarchy_node_id=b.id)
    admin_session.commit()
    denied = client.post(
        f"/api/soldiers/{target.id}/role", headers=auth_headers(dm), json={"role": "commander"}
    )
    assert denied.status_code == 403
    ok = client.post(
        f"/api/soldiers/{target.id}/role", headers=auth_headers(admin), json={"role": "commander"}
    )
    assert ok.status_code == 200
    assert ok.json()["role"] == "commander"


def test_soft_delete_sets_left_at(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000008", role="admin")
    target = create_soldier(admin_session, personal_number="4100007")
    r = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(admin))
    assert r.status_code == 204
    admin_session.expire_all()
    assert admin_session.get(type(target), target.id).left_at is not None
