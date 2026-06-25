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


def test_rbac_duty_config_role_gate(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5300001", role="admin")
    dm_node = create_node(admin_session, level="department", name="rbac-dc-node")
    dm = create_soldier(admin_session, personal_number="5300002", role="duty_manager", hierarchy_node_id=dm_node.id)
    cmd = create_soldier(admin_session, personal_number="5300003", role="commander")
    sol = create_soldier(admin_session, personal_number="5300004", role="soldier")
    payload = {"name": "rbac-dt", "score_per_day": "1.00", "is_external": False}
    assert (
        client.post(
            "/api/duty-config/duty-types", headers=auth_headers(admin), json=payload
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/duty-config/duty-types",
            headers=auth_headers(dm),
            json={"name": "rbac-dt2", "score_per_day": "1.00", "is_external": False},
        ).status_code
        == 201
    )
    assert client.get("/api/duty-config/duty-types", headers=auth_headers(cmd)).status_code == 403
    assert client.get("/api/duty-config/duty-types", headers=auth_headers(sol)).status_code == 403


def test_rbac_must_change_password_blocks_duty_config(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="department", name="rbac-mcp-node")
    dm = create_soldier(
        admin_session,
        personal_number="5300005",
        role="duty_manager",
        must_change_password=True,
        hierarchy_node_id=node.id,
    )
    r = client.get("/api/duty-config/duty-types", headers=auth_headers(dm))
    assert r.status_code == 403
    assert r.json()["detail"] == "must_change_password"


def test_dual_role_commander_can_manage_duty_config(client: TestClient, admin_session: Session):
    """A soldier who commands a node and is separately DM elsewhere must still be able
    to manage duty-config (a DM-global action) — role label alone must not gate this."""
    from app.db.models import DutyManagerScope

    a = create_node(admin_session, level="department", name="rbac-dual-a")
    b = create_node(admin_session, level="department", name="rbac-dual-b")
    dual = create_soldier(admin_session, personal_number="5300006", role="commander")
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    admin_session.commit()

    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(dual),
        json={"name": "rbac-dual-dt", "score_per_day": "1.00", "is_external": False},
    )
    assert r.status_code == 201
