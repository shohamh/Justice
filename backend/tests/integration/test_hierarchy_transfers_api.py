from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_create_and_approve_transfer_via_api(client: TestClient, admin_session: Session):
    src = create_node(admin_session, level="unit", name="api_src")
    dst = create_node(admin_session, level="unit", name="api_dst")
    soldier = create_soldier(admin_session, personal_number="7991001", hierarchy_node_id=src.id)
    admin = create_soldier(admin_session, personal_number="7991002", role="admin")
    admin_session.commit()

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(dst.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    req_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"
    assert resp.json()["from_node_id"] == str(src.id)
    assert resp.json()["to_node_id"] == str(dst.id)

    resp2 = client.post(f"/api/hierarchy-transfers/{req_id}/approve", headers=auth_headers(admin))
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "approved"


def test_reject_transfer_via_api(client: TestClient, admin_session: Session):
    src = create_node(admin_session, level="unit", name="api_src2")
    dst = create_node(admin_session, level="unit", name="api_dst2")
    soldier = create_soldier(admin_session, personal_number="7991003", hierarchy_node_id=src.id)
    admin = create_soldier(admin_session, personal_number="7991004", role="admin")
    admin_session.commit()

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(dst.id)},
        headers=auth_headers(admin),
    )
    req_id = resp.json()["id"]

    resp2 = client.post(
        f"/api/hierarchy-transfers/{req_id}/reject",
        json={"decision_note": "no room"},
        headers=auth_headers(admin),
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "rejected"


def test_commander_can_create_and_approve_hierarchy_transfer(client: TestClient, admin_session: Session):
    """A plain commander (not admin, not duty manager) who commands both the
    source and destination nodes must be able to create and approve a
    transfer request — regression test for the authorization gap where the
    route checked Action.SOLDIER_UPDATE (duty-manager-only) instead of a
    commander-reachable action."""
    cmd = create_soldier(admin_session, personal_number="7991010", role="commander")
    src = create_node(admin_session, level="unit", name="cmd_src", commander_id=cmd.id)
    dst = create_node(admin_session, level="unit", name="cmd_dst", commander_id=cmd.id)
    soldier = create_soldier(admin_session, personal_number="7991011", hierarchy_node_id=src.id)
    admin_session.commit()

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(dst.id)},
        headers=auth_headers(cmd),
    )
    assert resp.status_code == 200, resp.text
    req_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    resp2 = client.post(f"/api/hierarchy-transfers/{req_id}/approve", headers=auth_headers(cmd))
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["status"] == "approved"

    soldier_resp = client.get(f"/api/soldiers/{soldier.id}", headers=auth_headers(cmd))
    assert soldier_resp.status_code == 200, soldier_resp.text
    assert soldier_resp.json()["hierarchy_node_id"] == str(dst.id)


def test_list_pending_via_api(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7991005", role="admin")
    dst = create_node(admin_session, level="unit", name="api_dst3", commander_id=admin.id)
    soldier = create_soldier(admin_session, personal_number="7991006")
    admin_session.commit()

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(dst.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200

    resp2 = client.get("/api/hierarchy-transfers/pending", headers=auth_headers(admin))
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1
    assert resp2.json()[0]["soldier_id"] == str(soldier.id)


def test_requester_cannot_approve_own_transfer_into_own_command(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-self")
    b = create_node(admin_session, level="branch", name="b-self", parent=d)
    cmd = create_soldier(admin_session, personal_number="7700001", role="admin", hierarchy_node_id=d.id)
    b.commander_id = cmd.id
    admin_session.commit()

    r = client.post(
        "/api/hierarchy-transfers",
        headers=auth_headers(cmd),
        json={"soldier_id": str(cmd.id), "to_node_id": str(b.id)},
    )
    assert r.status_code == 200, r.text
    request_id = r.json()["id"]

    r2 = client.post(f"/api/hierarchy-transfers/{request_id}/approve", headers=auth_headers(cmd))
    assert r2.status_code == 403


def test_other_commander_can_still_approve(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-other")
    b = create_node(admin_session, level="branch", name="b-other", parent=d)
    dept_cmd = create_soldier(admin_session, personal_number="7700002", role="admin", hierarchy_node_id=d.id)
    d.commander_id = dept_cmd.id
    branch_cmd = create_soldier(admin_session, personal_number="7700003", role="admin", hierarchy_node_id=d.id)
    b.commander_id = branch_cmd.id
    admin_session.commit()

    r = client.post(
        "/api/hierarchy-transfers",
        headers=auth_headers(branch_cmd),
        json={"soldier_id": str(branch_cmd.id), "to_node_id": str(b.id)},
    )
    assert r.status_code == 200, r.text
    request_id = r.json()["id"]

    r2 = client.post(f"/api/hierarchy-transfers/{request_id}/approve", headers=auth_headers(dept_cmd))
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "approved"
