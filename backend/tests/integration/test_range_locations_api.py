from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_plain_soldier_can_list_range_locations(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6100001")
    r = client.get("/api/range-locations", headers=auth_headers(s))
    assert r.status_code == 200


def test_duty_manager_can_create_range_location(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="department", name="rl-dm-node")
    dm = create_soldier(admin_session, personal_number="6100002", role="duty_manager", hierarchy_node_id=node.id)
    r = client.post("/api/range-locations", headers=auth_headers(dm), json={"name": "מטווח חדש"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "מטווח חדש"
    assert body["active"] is True

    r2 = client.get("/api/range-locations", headers=auth_headers(dm))
    assert any(loc["id"] == body["id"] for loc in r2.json())


def test_plain_soldier_cannot_create_range_location(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6100003")
    r = client.post("/api/range-locations", headers=auth_headers(s), json={"name": "should_not_be_allowed"})
    assert r.status_code == 403
