from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.db.models import HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from app.services.invite_codes import create_invite_code
from tests.helpers import create_node


def _uid():
    return uuid.uuid4().hex[:8]


def _setup_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _payload(invite_code, node_id, **overrides):
    return {
        "invite_code": invite_code,
        "personal_number": f"pn_{_uid()}",
        "full_name": "Test Soldier",
        "password": "secure-password-1",
        "phone": "050-1234567",
        "email": "soldier@example.com",
        "gender": "male",
        "is_officer": False,
        "rank": "טוראי",
        "bahad1_graduate": False,
        # Relative to today so a חובה-only rank never accidentally looks like it
        # outlived its own mandatory-service window as the real calendar advances.
        "enlistment_date": (date.today() - timedelta(days=600)).isoformat(),
        "mandatory_end_date": (date.today() + timedelta(days=200)).isoformat(),
        "discharge_date": (date.today() + timedelta(days=600)).isoformat(),
        "last_mitvahim_date": (date.today() - timedelta(days=30)).isoformat(),
        "last_alal_date": None,
        "requested_node_id": str(node_id),
        "exemption_requests": [],
        "personal_constraints": [],
        **overrides,
    }


def test_register_rejects_missing_phone(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(invite.code, node.id)
    del payload["phone"]
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 422


def test_register_rejects_invalid_phone_format(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(invite.code, node.id, phone="not-a-phone-number")
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 422


def test_register_returns_access_token(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    resp = client.post("/api/auth/register", json=_payload(invite.code, node.id))
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_register_exhausted_code_returns_400(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=0, actor_id=None)
    admin_session.commit()

    resp = client.post("/api/auth/register", json=_payload(invite.code, node.id))
    assert resp.status_code == 400


def test_validate_code_endpoint(client, admin_session):
    invite = create_invite_code(admin_session, uses_left=3, actor_id=None)
    admin_session.commit()
    assert client.get(f"/api/auth/register/validate-code?code={invite.code}").json()["valid"] is True
    assert client.get("/api/auth/register/validate-code?code=INVALID1").json()["valid"] is False


def test_register_nodes_returns_list(client, admin_session):
    create_node(admin_session, level="division", name=f"div_{_uid()}")
    invite = create_invite_code(admin_session, uses_left=3, actor_id=None)
    admin_session.commit()
    resp = client.get(f"/api/auth/register/nodes?invite_code={invite.code}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_register_nodes_rejects_missing_code(client):
    resp = client.get("/api/auth/register/nodes")
    assert resp.status_code == 422


def test_register_nodes_rejects_invalid_code(client):
    resp = client.get("/api/auth/register/nodes?invite_code=INVALID-CODE-XYZ")
    assert resp.status_code == 403


def test_register_rejects_partial_exemption_request(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(
        invite.code, node.id,
        exemption_requests=[{"exemption_type_id": "", "start_date": "", "end_date": "", "reason": ""}],
    )
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "exemption_missing_fields"
