from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_effort_gap_endpoint_returns_all_nodes(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="Effort Gap API Co")
    admin = create_soldier(admin_session, personal_number="5700001", role="admin")

    resp = client.get("/api/potential/effort-gap", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert str(node.id) in node_ids
    entry = next(n for n in body["nodes"] if n["node_id"] == str(node.id))
    assert "sibling_gap" in entry
    assert "global_gap" in entry


def test_effort_gap_endpoint_scopes_to_duty_manager(client: TestClient, admin_session: Session):
    in_scope_node = create_node(admin_session, level="unit", name="In Scope Co")
    out_of_scope_node = create_node(admin_session, level="unit", name="Out Of Scope Co")
    dm = create_soldier(
        admin_session,
        personal_number="5700002",
        role="duty_manager",
        hierarchy_node_id=in_scope_node.id,
    )

    resp = client.get("/api/potential/effort-gap", headers=auth_headers(dm))
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["node_id"] for n in body["nodes"]}
    assert str(in_scope_node.id) in node_ids
    assert str(out_of_scope_node.id) not in node_ids
