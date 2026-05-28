from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_must_change_password_blocks_protected_endpoints(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(
        admin_session, personal_number="3000001", role="admin", must_change_password=True
    )
    r = client.get("/api/soldiers", headers=auth_headers(admin))
    assert r.status_code == 403
    assert r.json()["detail"] == "must_change_password"
    assert client.get("/api/me", headers=auth_headers(admin)).status_code == 200


def test_commander_reads_subtree_cannot_write(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="3000002", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    member = create_soldier(admin_session, personal_number="3100001", hierarchy_node_id=b.id)
    admin_session.commit()
    assert client.get(f"/api/soldiers/{member.id}", headers=auth_headers(cmd)).status_code == 200
    denied = client.post(
        "/api/soldiers",
        headers=auth_headers(cmd),
        json={"personal_number": "3100002", "full_name": "x", "hierarchy_node_id": str(b.id)},
    )
    assert denied.status_code == 403


def test_soldier_sees_only_self_in_list(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(
        admin_session, personal_number="3000003", role="soldier", hierarchy_node_id=d.id
    )
    create_soldier(admin_session, personal_number="3100003", hierarchy_node_id=d.id)
    admin_session.commit()
    r = client.get("/api/soldiers", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1 and body[0]["personal_number"] == "3000003"
