"""Integration tests for private-field access control across all routes."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session: Session, name: str) -> ExemptionType:
    et = ExemptionType(name=name)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


# ── Soldier private fields ───────────────────────────────────────────────────


def test_admin_cannot_see_gender_but_sees_phone_email_by_default(client: TestClient, admin_session: Session):
    """gender stays private-scope-gated; phone/email are public by default
    (soldiers.phone_public / soldiers.email_public) so an admin with no
    scope over the target still sees them — see test_private_fields.py's
    test_admin_cannot_see_phone_email_when_public_settings_disabled for the
    opposite case."""
    admin = create_soldier(admin_session, personal_number="pf-adm001", role="admin")
    d = create_node(admin_session, level="department", name="pf-d1")
    dm = create_soldier(admin_session, personal_number="pf-dm001", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s001", hierarchy_node_id=d.id)
    target.phone = "0501234567"
    target.email = "pf-target@example.com"
    admin_session.commit()
    # DM sets profile with private fields
    client.patch(
        f"/api/soldiers/{target.id}/profile",
        json={"gender": "male"},
        headers=auth_headers(dm),
    )
    # Admin fetches individual soldier
    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["gender"] is None
    assert body["phone"] == "0501234567"
    assert body["email"] == "pf-target@example.com"


def test_admin_cannot_see_phone_email_when_public_settings_disabled(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting

    set_setting(admin_session, "soldiers.phone_public", False, actor_id=None)
    set_setting(admin_session, "soldiers.email_public", False, actor_id=None)
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number="pf-adm005", role="admin")
    d = create_node(admin_session, level="department", name="pf-d5")
    target = create_soldier(admin_session, personal_number="pf-s005", hierarchy_node_id=d.id)
    target.phone = "0501234567"
    target.email = "pf-target5@example.com"
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] is None
    assert body["email"] is None


def test_admin_list_soldiers_private_fields_null(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm002", role="admin")
    d = create_node(admin_session, level="department", name="pf-d2")
    dm = create_soldier(admin_session, personal_number="pf-dm002", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s002", hierarchy_node_id=d.id)
    admin_session.commit()
    client.patch(
        f"/api/soldiers/{target.id}/profile",
        json={"gender": "female"},
        headers=auth_headers(dm),
    )
    r = client.get("/api/soldiers", headers=auth_headers(admin))
    assert r.status_code == 200
    rows = {s["id"]: s for s in r.json()}
    row = rows[str(target.id)]
    assert row["gender"] is None


def test_dm_in_scope_can_see_gender(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d3")
    dm = create_soldier(admin_session, personal_number="pf-dm003", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s003", hierarchy_node_id=d.id)
    admin_session.commit()
    client.patch(
        f"/api/soldiers/{target.id}/profile",
        json={"gender": "male"},
        headers=auth_headers(dm),
    )
    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(dm))
    assert r.status_code == 200
    assert r.json()["gender"] == "male"


def test_plain_soldier_cannot_see_peer_gender(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d4")
    dm = create_soldier(admin_session, personal_number="pf-dm004", role="duty_manager", hierarchy_node_id=d.id)
    viewer = create_soldier(admin_session, personal_number="pf-s004a", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s004b", hierarchy_node_id=d.id)
    admin_session.commit()
    client.patch(
        f"/api/soldiers/{target.id}/profile",
        json={"gender": "female"},
        headers=auth_headers(dm),
    )
    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(viewer))
    # Plain soldiers can view another soldier's basic profile (read-only),
    # but private fields like gender stay redacted since the viewer has no
    # command/duty-manager scope over the target.
    assert r.status_code == 200
    assert r.json()["gender"] is None


# ── Field-update redaction ───────────────────────────────────────────────────


def test_admin_sees_redacted_values_for_private_field_updates(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm003", role="admin")
    d = create_node(admin_session, level="department", name="pf-d5")
    target = create_soldier(admin_session, personal_number="pf-s005", hierarchy_node_id=d.id)
    admin_session.commit()
    # target submits a gender field update
    client.post(
        f"/api/soldiers/{target.id}/field-updates",
        json={"field_name": "gender", "new_value": "male"},
        headers=auth_headers(target),
    )
    r = client.get("/api/soldiers/field-updates/pending", headers=auth_headers(admin))
    assert r.status_code == 200
    items = [i for i in r.json() if i["soldier_id"] == str(target.id) and i["field_name"] == "gender"]
    assert len(items) == 1
    assert items[0]["new_value"] is None


def test_dm_sees_real_values_for_private_field_updates(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d6")
    dm = create_soldier(admin_session, personal_number="pf-dm005", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s006", hierarchy_node_id=d.id)
    admin_session.commit()
    client.post(
        f"/api/soldiers/{target.id}/field-updates",
        json={"field_name": "gender", "new_value": "female"},
        headers=auth_headers(target),
    )
    r = client.get("/api/soldiers/field-updates/pending", headers=auth_headers(dm))
    assert r.status_code == 200
    items = [i for i in r.json() if i["soldier_id"] == str(target.id) and i["field_name"] == "gender"]
    assert len(items) == 1
    assert items[0]["new_value"] == "female"


# ── Constraint reason ────────────────────────────────────────────────────────


def test_admin_cannot_see_constraint_reason_in_pending_list(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm004", role="admin")
    d = create_node(admin_session, level="department", name="pf-d7")
    target = create_soldier(admin_session, personal_number="pf-s007", hierarchy_node_id=d.id)
    admin_session.commit()
    client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={"start_date": "2026-08-01", "end_date": "2026-08-05", "reason": "סיבה פרטית"},
    )
    r = client.get("/api/constraints/pending", headers=auth_headers(admin))
    assert r.status_code == 200
    rows = [row for row in r.json() if row["soldier_id"] == str(target.id)]
    assert len(rows) == 1
    assert rows[0]["reason"] is None


def test_dm_can_see_constraint_reason_in_pending_list(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d8")
    dm = create_soldier(admin_session, personal_number="pf-dm006", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s008", hierarchy_node_id=d.id)
    admin_session.commit()
    client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={"start_date": "2026-08-01", "end_date": "2026-08-05", "reason": "חופשה"},
    )
    r = client.get("/api/constraints/pending", headers=auth_headers(dm))
    assert r.status_code == 200
    rows = [row for row in r.json() if row["soldier_id"] == str(target.id)]
    assert len(rows) == 1
    assert rows[0]["reason"] == "חופשה"


def test_self_can_see_own_constraint_reason(client: TestClient, admin_session: Session):
    target = create_soldier(admin_session, personal_number="pf-s009")
    admin_session.commit()
    client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={"start_date": "2026-08-01", "end_date": "2026-08-05", "reason": "פרטי"},
    )
    r = client.get("/api/me/constraints", headers=auth_headers(target))
    assert r.status_code == 200
    assert r.json()[0]["reason"] == "פרטי"


# ── Exemption sensitive fields ───────────────────────────────────────────────


def test_admin_cannot_see_exemption_type_or_reason(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm005", role="admin")
    d = create_node(admin_session, level="department", name="pf-d9")
    dm = create_soldier(admin_session, personal_number="pf-dm007", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s010", hierarchy_node_id=d.id)
    et = _et(admin_session, "pf-et-001")
    admin_session.commit()
    client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(dm),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "סיבה"},
    )
    r = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin))
    assert r.status_code == 200
    exs = r.json()
    assert len(exs) == 1
    assert exs[0]["reason"] is None
    assert exs[0]["exemption_type_id"] is None


def test_dm_can_see_exemption_type_and_reason(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d10")
    dm = create_soldier(admin_session, personal_number="pf-dm008", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s011", hierarchy_node_id=d.id)
    et = _et(admin_session, "pf-et-002")
    admin_session.commit()
    client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(dm),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "סיבה"},
    )
    r = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(dm))
    assert r.status_code == 200
    exs = r.json()
    assert exs[0]["reason"] == "סיבה"
    assert exs[0]["exemption_type_id"] == str(et.id)


def test_self_can_see_own_exemption_type_and_reason(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d11")
    dm = create_soldier(admin_session, personal_number="pf-dm009", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s012", hierarchy_node_id=d.id)
    et = _et(admin_session, "pf-et-003")
    admin_session.commit()
    client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(dm),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "טעם"},
    )
    r = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(target))
    assert r.status_code == 200
    exs = r.json()
    assert exs[0]["reason"] == "טעם"
    assert exs[0]["exemption_type_id"] == str(et.id)
