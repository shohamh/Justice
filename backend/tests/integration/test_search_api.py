from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_search_requires_auth(client: TestClient):
    r = client.get("/api/search?q=test")
    assert r.status_code == 401


def test_search_empty_query_returns_empty_groups(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7500001", role="admin")

    r = client.get("/api/search?q=", headers=auth_headers(admin))

    assert r.status_code == 200
    body = r.json()
    assert body == {"soldiers": [], "duties": [], "units": []}


def test_search_returns_grouped_results_for_admin(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7500002", role="admin")
    target = create_soldier(admin_session, personal_number="7500003", role="soldier")
    target.full_name = "Search-Target Person"
    admin_session.commit()

    r = client.get("/api/search?q=Search-Target", headers=auth_headers(admin))

    assert r.status_code == 200
    body = r.json()
    assert any(s["id"] == str(target.id) for s in body["soldiers"])
    assert body["duties"] == []
    assert body["units"] == []


def test_search_plain_soldier_never_sees_out_of_scope_soldier(client: TestClient, admin_session: Session):
    dept = create_node(admin_session, level="department", name="api-search-dept")
    other_dept = create_node(admin_session, level="department", name="api-search-dept-2")
    plain = create_soldier(admin_session, personal_number="7500010", role="soldier", hierarchy_node_id=dept.id)
    outsider = create_soldier(admin_session, personal_number="7500011", role="soldier", hierarchy_node_id=other_dept.id)
    outsider.full_name = "Outside-Scope-Person"
    admin_session.commit()

    r = client.get("/api/search?q=Outside-Scope", headers=auth_headers(plain))

    assert r.status_code == 200
    body = r.json()
    assert body["soldiers"] == []
