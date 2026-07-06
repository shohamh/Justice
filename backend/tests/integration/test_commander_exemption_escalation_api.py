from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session, name, is_commander_exemption=False):
    et = ExemptionType(name=name, is_commander_exemption=is_commander_exemption)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


def test_admin_escalates_with_apply_immediately(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    target = create_soldier(admin_session, personal_number="5300001", hierarchy_node_id=d.id)
    admin = create_soldier(admin_session, personal_number="5300002", role="admin")
    official = _et(admin_session, "פטור-אסק-1")
    commander_type = _et(admin_session, "פטור-פיקודי-אסק-1", is_commander_exemption=True)

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(admin),
        json={
            "official_exemption_type_id": str(official.id),
            "commander_exemption_type_id": str(commander_type.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending_duty_manager"

    from app.db.models import SoldierExemption
    from sqlalchemy import select
    granted = admin_session.execute(
        select(SoldierExemption).where(SoldierExemption.soldier_id == target.id)
    ).scalars().all()
    assert len(granted) == 1
    assert granted[0].exemption_type_id == commander_type.id


def test_admin_escalates_request_only(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d2")
    target = create_soldier(admin_session, personal_number="5300003", hierarchy_node_id=d.id)
    admin = create_soldier(admin_session, personal_number="5300004", role="admin")
    official = _et(admin_session, "פטור-אסק-2")

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(admin),
        json={
            "official_exemption_type_id": str(official.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": False,
        },
    )
    assert r.status_code == 201, r.text
    exemptions = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin)).json()
    assert exemptions == []


def test_out_of_scope_commander_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d3")
    other = create_node(admin_session, level="department", name="other3")
    cmd = create_soldier(admin_session, personal_number="5300005", role="commander")
    other.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5300006", hierarchy_node_id=d.id)
    official = _et(admin_session, "פטור-אסק-3")

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(cmd),
        json={
            "official_exemption_type_id": str(official.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": False,
        },
    )
    assert r.status_code == 403


def test_escalate_rejects_commander_type_as_official_target(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d4")
    target = create_soldier(admin_session, personal_number="5300007", hierarchy_node_id=d.id)
    admin = create_soldier(admin_session, personal_number="5300008", role="admin")
    commander_type = _et(admin_session, "פטור-פיקודי-אסק-4", is_commander_exemption=True)

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(admin),
        json={
            "official_exemption_type_id": str(commander_type.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": False,
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "official_exemption_type_required"


def test_soldier_exemption_request_history_shows_all_statuses(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d5")
    target = create_soldier(admin_session, personal_number="5300009", hierarchy_node_id=d.id)
    admin = create_soldier(admin_session, personal_number="5300010", role="admin")
    official = _et(admin_session, "פטור-אסק-5")

    req = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(admin),
        json={
            "official_exemption_type_id": str(official.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": False,
        },
    ).json()
    client.post(
        f"/api/exemption-requests/{req['id']}/reject",
        headers=auth_headers(admin),
        json={"decision_note": "לא רלוונטי"},
    )

    r = client.get(f"/api/soldiers/{target.id}/exemption-requests", headers=auth_headers(admin))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"


def test_soldier_cannot_read_others_exemption_request_history(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d6")
    target = create_soldier(admin_session, personal_number="5300011", hierarchy_node_id=d.id)
    other_soldier = create_soldier(admin_session, personal_number="5300012")

    r = client.get(f"/api/soldiers/{target.id}/exemption-requests", headers=auth_headers(other_soldier))
    assert r.status_code == 403
