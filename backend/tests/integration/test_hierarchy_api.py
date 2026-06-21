from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_creates_division_then_unit(client: TestClient, admin_session: Session):
    corps = create_node(admin_session, level="corps", name="כלל המסגרת")
    admin_session.commit()
    admin = create_soldier(admin_session, personal_number="5000001", role="admin")
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "division", "name": "מערך", "parent_id": str(corps.id)},
    )
    assert r.status_code == 201
    div_id = r.json()["id"]
    r2 = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "unit", "name": "יחידה", "parent_id": div_id},
    )
    assert r2.status_code == 201
    assert r2.json()["path_ids"] == [str(corps.id), div_id, r2.json()["id"]]


def test_create_any_level_below_allowed(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000002", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "team", "name": "צוות", "parent_id": str(dept.id)},
    )
    assert r.status_code == 201


def test_plain_soldier_cannot_create_node(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5000003", role="soldier")
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(s),
        json={"level": "department", "name": "x", "parent_id": None},
    )
    assert r.status_code == 403


def test_get_tree_scoped_for_duty_manager(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(
        admin_session, personal_number="5000004", role="duty_manager", hierarchy_node_id=b.id
    )
    admin_session.commit()
    r = client.get("/api/hierarchy/tree", headers=auth_headers(dm))
    assert r.status_code == 200
    ids = {n["id"] for n in r.json()}
    assert str(b.id) in ids
    assert str(other.id) not in ids
