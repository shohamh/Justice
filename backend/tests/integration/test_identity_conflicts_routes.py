"""Admin identity conflict endpoints."""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import AuditLog
from app.services.identity_resolution import (
    Candidate,
    record_identity_conflict,
)
from tests.helpers import auth_headers, create_node, create_soldier, set_soldier_email


def _setup(session):
    node = create_node(session, level="department", name="ic-node")
    admin = create_soldier(session, personal_number="ic-adm", role="admin")
    dm = create_soldier(session, personal_number="ic-dm", role="duty_manager", hierarchy_node_id=node.id)
    a = create_soldier(session, personal_number="ic-a", full_name="Alice Cohen")
    set_soldier_email(a, "dude@corp.example")
    b = create_soldier(session, personal_number="ic-b", full_name="Bob Levi")
    set_soldier_email(b, "b@b.example")
    session.commit()
    conflict = record_identity_conflict(
        session, source="sso", ad_username="dude",
        candidates=[
            Candidate(soldier_id=a.id, matched_fields=("ad_username",)),
            Candidate(soldier_id=b.id, matched_fields=("email",)),
        ],
    )
    session.commit()
    return admin, dm, a, b, conflict


def test_list_requires_admin(client, admin_session):
    admin, dm, _a, _b, _c = _setup(admin_session)
    plain = create_soldier(admin_session, personal_number="ic-plain")
    assert client.get("/api/admin/identity-conflicts").status_code in (401, 403)
    assert client.get("/api/admin/identity-conflicts", headers=auth_headers(plain)).status_code == 403
    assert client.get("/api/admin/identity-conflicts", headers=auth_headers(dm)).status_code == 403
    assert client.get("/api/admin/identity-conflicts", headers=auth_headers(admin)).status_code == 200


def test_list_open_conflicts_with_masked_candidates(client, admin_session):
    admin, _dm, a, b, conflict = _setup(admin_session)
    resp = client.get("/api/admin/identity-conflicts", headers=auth_headers(admin))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == str(conflict.id)
    assert (item["source"], item["status"], item["ad_username"]) == ("sso", "open", "dude")
    by_id = {c["soldier_id"]: c for c in item["candidates"]}
    assert set(by_id) == {str(a.id), str(b.id)}
    assert by_id[str(a.id)]["full_name"] == "Alice Cohen"
    assert by_id[str(a.id)]["personal_number"] == "ic-a"
    assert by_id[str(a.id)]["matched_fields"] == ["ad_username"]
    assert by_id[str(a.id)]["email_masked"] == "d***@c***.example"
    assert by_id[str(a.id)]["active"] is True
    assert "dude@corp.example" not in resp.text


def test_resolve_chooses_candidate_and_audits(client, admin_session):
    admin, _dm, a, _b, conflict = _setup(admin_session)
    resp = client.post(f"/api/admin/identity-conflicts/{conflict.id}/resolve",
                       json={"soldier_id": str(a.id)}, headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert resp.json()["chosen_soldier_id"] == str(a.id)
    audit = admin_session.execute(
        select(AuditLog).where(AuditLog.action == "identity_conflict.resolve")
    ).scalar_one()
    assert audit.actor_id == admin.id and audit.entity_id == conflict.id
    assert audit.after["chosen_soldier_id"] == str(a.id)
    assert "corp.example" not in str(audit.after)
    listing = client.get("/api/admin/identity-conflicts", headers=auth_headers(admin)).json()["items"]
    assert listing == []
    assert client.post(f"/api/admin/identity-conflicts/{conflict.id}/resolve",
                       json={"soldier_id": str(a.id)}, headers=auth_headers(admin)).status_code == 409


def test_resolve_rejects_non_candidate_and_non_admin(client, admin_session):
    admin, dm, _a, _b, conflict = _setup(admin_session)
    stranger = create_soldier(admin_session, personal_number="ic-x")
    r = client.post(f"/api/admin/identity-conflicts/{conflict.id}/resolve",
                    json={"soldier_id": str(stranger.id)}, headers=auth_headers(admin))
    assert r.status_code == 400
    assert r.json()["detail"] == "not_a_candidate"
    r = client.post(f"/api/admin/identity-conflicts/{conflict.id}/resolve",
                    json={"soldier_id": str(stranger.id)}, headers=auth_headers(dm))
    assert r.status_code == 403


def test_dismiss_requires_reason_and_audits(client, admin_session):
    admin, dm, _a, _b, conflict = _setup(admin_session)
    url = f"/api/admin/identity-conflicts/{conflict.id}/dismiss"
    assert client.post(url, json={"reason": "x"}, headers=auth_headers(dm)).status_code == 403
    assert client.post(url, json={"reason": "  "}, headers=auth_headers(admin)).status_code == 400
    ok = client.post(url, json={"reason": "reported twice"}, headers=auth_headers(admin))
    assert ok.status_code == 200
    assert ok.json()["status"] == "dismissed"
    audit = admin_session.execute(
        select(AuditLog).where(AuditLog.action == "identity_conflict.dismiss")
    ).scalar_one()
    assert audit.after["reason"] == "reported twice"
    assert client.post(url, json={"reason": "again"}, headers=auth_headers(admin)).status_code == 409


def test_unknown_conflict_is_404(client, admin_session):
    admin, *_ = _setup(admin_session)
    import uuid
    r = client.post(f"/api/admin/identity-conflicts/{uuid.uuid4()}/dismiss",
                    json={"reason": "x"}, headers=auth_headers(admin))
    assert r.status_code == 404
