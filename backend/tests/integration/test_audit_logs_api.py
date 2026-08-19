from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType, PersonalConstraint
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session, name):
    et = ExemptionType(name=name)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


def test_rejects_unsupported_entity_type(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8100001")
    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier", "entity_id": str(s.id)},
        headers=auth_headers(s),
    )
    assert r.status_code == 400, r.text


def test_soldier_sees_own_exemption_history(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8100002", role="admin")
    s = create_soldier(admin_session, personal_number="8100003")
    et = _et(admin_session, "פטור-ה1")
    grant = client.post(
        f"/api/soldiers/{s.id}/exemptions",
        headers=auth_headers(admin),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "רפואי"},
    )
    assert grant.status_code == 201, grant.text
    exemption_id = grant.json()["id"]

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier_exemption", "entity_id": exemption_id},
        headers=auth_headers(s),
    )
    assert r.status_code == 200, r.text
    entries = r.json()
    assert len(entries) == 1
    assert entries[0]["action"] == "exemption.grant"
    assert entries[0]["actor_name"] == admin.full_name
    assert entries[0]["entity_type"] == "soldier_exemption"
    assert entries[0]["created_at"]


def test_commander_in_subtree_sees_exemption_history(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-audit1")
    b = create_node(admin_session, level="branch", name="b-audit1", parent=d)
    cmd = create_soldier(admin_session, personal_number="8100003", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="8100004", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-ה2")
    grant = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    assert grant.status_code == 201, grant.text
    exemption_id = grant.json()["id"]

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier_exemption", "entity_id": exemption_id},
        headers=auth_headers(cmd),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["action"] == "exemption.grant"


def test_commander_outside_subtree_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-audit2")
    b = create_node(admin_session, level="branch", name="b-audit2", parent=d)
    other = create_node(admin_session, level="department", name="other-audit2")
    cmd = create_soldier(admin_session, personal_number="8100005", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="8100006", hierarchy_node_id=other.id)
    et = _et(admin_session, "פטור-ה3")

    # Grant directly through the service layer (rather than the HTTP POST
    # endpoint) since no in-scope actor for `other` exists in this test —
    # the point of this test is read-side scoping, not the grant path.
    from app.services import exemptions as exemptions_svc

    ex = exemptions_svc.grant_exemption(
        admin_session, soldier_id=target.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None, reason=None, actor_id=target.id,
    )
    admin_session.commit()

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier_exemption", "entity_id": str(ex.id)},
        headers=auth_headers(cmd),
    )
    assert r.status_code == 403, r.text


def test_soldier_sees_own_constraint_history(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8100007")
    submit = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    )
    assert submit.status_code == 201, submit.text
    constraint_id = submit.json()["id"]

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "personal_constraint", "entity_id": constraint_id},
        headers=auth_headers(s),
    )
    assert r.status_code == 200, r.text
    entries = r.json()
    assert len(entries) == 1
    assert entries[0]["action"] == "constraint.submit"


def test_history_survives_constraint_hard_delete_on_cancel(client: TestClient, admin_session: Session):
    """Regression test for the exact gap item 17 reports: after a constraint
    is canceled, its PersonalConstraint row is hard-deleted (see
    cancel_constraint in backend/app/services/constraints.py), but the audit
    trail — including the cancellation itself — must still be readable."""
    s = create_soldier(admin_session, personal_number="8100008")
    submit = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    )
    assert submit.status_code == 201, submit.text
    constraint_id = submit.json()["id"]

    cancel = client.delete(f"/api/me/constraints/{constraint_id}", headers=auth_headers(s))
    assert cancel.status_code == 204, cancel.text

    # The row is really gone.
    assert admin_session.get(PersonalConstraint, constraint_id) is None

    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "personal_constraint", "entity_id": constraint_id},
        headers=auth_headers(s),
    )
    assert r.status_code == 200, r.text
    actions = {e["action"] for e in r.json()}
    assert actions == {"constraint.submit", "constraint.cancel"}


def test_not_found_for_unknown_entity_id(client: TestClient, admin_session: Session):
    import uuid

    s = create_soldier(admin_session, personal_number="8100009")
    r = client.get(
        "/api/audit-logs",
        params={"entity_type": "soldier_exemption", "entity_id": str(uuid.uuid4())},
        headers=auth_headers(s),
    )
    assert r.status_code == 404, r.text
