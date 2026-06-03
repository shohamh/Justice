from __future__ import annotations
import uuid
from tests.helpers import auth_headers, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_admin_creates_code(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    resp = client.post("/api/admin/invite-codes", json={"uses_left": 5}, headers=auth_headers(admin))
    assert resp.status_code == 201
    assert resp.json()["uses_left"] == 5
    assert len(resp.json()["code"]) == 8


def test_non_admin_forbidden(client, admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    resp = client.post("/api/admin/invite-codes", json={"uses_left": 1}, headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_admin_lists_codes(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    client.post("/api/admin/invite-codes", json={"uses_left": 1}, headers=auth_headers(admin))
    resp = client.get("/api/admin/invite-codes", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_admin_revokes_code(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    create_resp = client.post("/api/admin/invite-codes", json={"uses_left": 2}, headers=auth_headers(admin))
    code_id = create_resp.json()["id"]
    resp = client.delete(f"/api/admin/invite-codes/{code_id}", headers=auth_headers(admin))
    assert resp.status_code == 200
