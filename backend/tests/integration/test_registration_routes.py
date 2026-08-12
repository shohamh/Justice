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


def test_register_stores_military_driving_license(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(
        invite.code, node.id,
        has_military_driving_license=True,
        military_driving_license_expiry=(date.today() + timedelta(days=365)).isoformat(),
    )
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 200

    from app.db.models import Soldier
    soldier = admin_session.query(Soldier).filter_by(personal_number=payload["personal_number"]).one()
    assert soldier.has_military_driving_license is True
    assert soldier.military_driving_license_expiry == date.today() + timedelta(days=365)


def test_register_defaults_military_driving_license_to_false(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(invite.code, node.id)
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 200

    from app.db.models import Soldier
    soldier = admin_session.query(Soldier).filter_by(personal_number=payload["personal_number"]).one()
    assert soldier.has_military_driving_license is False
    assert soldier.military_driving_license_expiry is None


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


def test_register_accepts_permanent_exemption_row(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    from app.db.models import ExemptionType
    et = ExemptionType(name=f"פטור-reg-permanent-{_uid()}", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    payload = _payload(invite.code, node.id, exemption_requests=[
        {"exemption_type_id": str(et.id), "start_date": None, "end_date": None, "reason": "פטור קבוע"},
    ])
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 200, resp.text

    from app.db.models import ExemptionRequest
    req = admin_session.query(ExemptionRequest).filter_by(exemption_type_id=et.id).one()
    assert req.start_date is None
    assert req.end_date is None


def test_register_rejects_exemption_row_with_end_date_but_no_start_date(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    from app.db.models import ExemptionType
    et = ExemptionType(name=f"פטור-reg-badrow-{_uid()}", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    payload = _payload(invite.code, node.id, exemption_requests=[
        {"exemption_type_id": str(et.id), "start_date": None,
         "end_date": (date.today() + timedelta(days=10)).isoformat(), "reason": "x"},
    ])
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "start_date_required"


def test_public_exemption_types_expose_is_medical(client, admin_session):
    from app.db.models import ExemptionType
    et = ExemptionType(name=f"פטור-medical-{_uid()}", is_commander_exemption=False, is_medical=True)
    admin_session.add(et)
    admin_session.commit()

    resp = client.get("/api/auth/exemption-types")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == str(et.id))
    assert row["is_medical"] is True
