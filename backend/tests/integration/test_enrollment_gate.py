from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def _make_probe_app(real_app):
    """Mount a throwaway endpoint gated by require_enrolled onto the real app,
    reusing its already-wired get_session override."""
    from fastapi import Depends

    from app.auth.deps import require_enrolled

    @real_app.get("/__probe/require_enrolled")
    def _probe(user=Depends(require_enrolled)):
        return {"id": str(user.id)}


def test_soldier_with_pending_enrollment_is_blocked(client: TestClient, admin_session: Session):
    from app.db.models import SoldierEnrollmentRequest

    _make_probe_app(client.app)
    node = create_node(admin_session, level="unit", name="probe_unit_pending")
    s = create_soldier(admin_session, personal_number="7600001", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()

    r = client.get("/__probe/require_enrolled", headers=auth_headers(s))
    assert r.status_code == 403
    assert r.json()["detail"] == "enrollment_pending"


def test_soldier_with_commander_approved_enrollment_is_blocked(client: TestClient, admin_session: Session):
    from app.db.models import SoldierEnrollmentRequest

    _make_probe_app(client.app)
    node = create_node(admin_session, level="unit", name="probe_unit_commander_approved")
    s = create_soldier(admin_session, personal_number="7600002", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="commander_approved"))
    admin_session.commit()

    r = client.get("/__probe/require_enrolled", headers=auth_headers(s))
    assert r.status_code == 403


def test_soldier_with_approved_enrollment_passes(client: TestClient, admin_session: Session):
    from app.db.models import SoldierEnrollmentRequest

    _make_probe_app(client.app)
    node = create_node(admin_session, level="unit", name="probe_unit_approved")
    s = create_soldier(admin_session, personal_number="7600003", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="approved"))
    admin_session.commit()

    r = client.get("/__probe/require_enrolled", headers=auth_headers(s))
    assert r.status_code == 200


def test_soldier_with_no_enrollment_request_passes(client: TestClient, admin_session: Session):
    _make_probe_app(client.app)
    s = create_soldier(admin_session, personal_number="7600004")

    r = client.get("/__probe/require_enrolled", headers=auth_headers(s))
    assert r.status_code == 200
