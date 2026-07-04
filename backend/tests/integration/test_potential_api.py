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
