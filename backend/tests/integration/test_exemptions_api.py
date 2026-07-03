from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session, name):
    et = ExemptionType(name=name)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


def test_commander_grants_in_subtree(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="5200001", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5200002", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-ר1")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "גב"},
    )
    assert r.status_code == 201, r.text
    r2 = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(cmd))
    assert len(r2.json()) == 1


def test_commander_out_of_subtree_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="5200003", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5200004", hierarchy_node_id=other.id)
    et = _et(admin_session, "פטור-ר2")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    assert r.status_code == 403


def test_soldier_reads_own_but_cannot_grant(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5200005", role="soldier")
    et = _et(admin_session, "פטור-ר3")
    r = client.get(f"/api/soldiers/{s.id}/exemptions", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json() == []
    r2 = client.post(
        f"/api/soldiers/{s.id}/exemptions",
        headers=auth_headers(s),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    assert r2.status_code == 403


def test_revoke_active_soft(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200006", role="admin")
    target = create_soldier(admin_session, personal_number="5200007")
    et = _et(admin_session, "פטור-ר4")
    ex = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(admin),
        json={
            "exemption_type_id": str(et.id),
            "start_date": (date.today() - timedelta(days=2)).isoformat(),
        },
    ).json()
    r = client.delete(
        f"/api/soldiers/{target.id}/exemptions/{ex['id']}", headers=auth_headers(admin)
    )
    assert r.status_code == 204
    rows = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin)).json()
    assert rows[0]["end_date"] == date.today().isoformat()


def test_revoke_rejects_cross_soldier_id(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200008", role="admin")
    a = create_soldier(admin_session, personal_number="5200009")
    b = create_soldier(admin_session, personal_number="5200010")
    et = _et(admin_session, "פטור-ר5")
    ex = client.post(
        f"/api/soldiers/{a.id}/exemptions",
        headers=auth_headers(admin),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    ).json()
    r = client.delete(f"/api/soldiers/{b.id}/exemptions/{ex['id']}", headers=auth_headers(admin))
    assert r.status_code == 404


def test_patch_pending_commander_request_succeeds(client: TestClient, admin_session: Session):
    """Regression test: the PATCH route's pending-status check still referenced the
    single old "pending" status after it was split into pending_commander/pending_duty_manager,
    which made this endpoint unconditionally reject every request. Confirms it now accepts
    a request in either new pending sub-state."""
    admin = create_soldier(admin_session, personal_number="5200011", role="admin")
    soldier = create_soldier(admin_session, personal_number="5200012")
    et = _et(admin_session, "פטור-ר6")
    req = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(soldier),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    ).json()
    assert req["status"] == "pending_commander"
    r = client.patch(
        f"/api/exemption-requests/{req['id']}",
        headers=auth_headers(admin),
        json={"reason": "updated reason"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_commander"


def test_patch_rejects_retargeting_to_commander_exemption_type(client: TestClient, admin_session: Session):
    """A pending request's exemption_type_id must not be retargeted to a
    commander-exemption type — that would bypass the rank/level gate that
    grant_commander_exemption otherwise enforces."""
    admin = create_soldier(admin_session, personal_number="5200013", role="admin")
    soldier = create_soldier(admin_session, personal_number="5200014")
    regular = _et(admin_session, "פטור-ר7")
    commander_et = ExemptionType(name="פטור-פיקודי-ר7", is_commander_exemption=True)
    admin_session.add(commander_et)
    admin_session.commit()
    req = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(soldier),
        json={"exemption_type_id": str(regular.id), "start_date": "2026-01-01"},
    ).json()
    r = client.patch(
        f"/api/exemption-requests/{req['id']}",
        headers=auth_headers(admin),
        json={"exemption_type_id": str(commander_et.id)},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "commander_exemption_not_requestable"
