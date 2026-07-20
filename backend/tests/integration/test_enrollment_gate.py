from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyType, SoldierEnrollmentRequest
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


def _make_assignment(session, *, soldier, node):
    dt = DutyType(name="probe_duty_type", score_per_day=1)
    loc = DutyLocation(name="probe_duty_location")
    session.add_all([dt, loc])
    session.flush()
    a = DutyAssignment(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=3),
        end_date=date.today() + timedelta(days=4),
        status="published",
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_pending_soldier_cannot_create_swap(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="probe_unit_swap")
    s = create_soldier(admin_session, personal_number="7600010", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()
    assignment = _make_assignment(admin_session, soldier=s, node=node)

    r = client.post(
        "/api/me/swaps",
        headers=auth_headers(s),
        json={"duty_assignment_id": str(assignment.id), "target_soldier_id": None, "reason": None},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "enrollment_pending"


def test_pending_soldier_cannot_submit_constraint(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="probe_unit_constraint")
    s = create_soldier(admin_session, personal_number="7600011", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()

    r = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "test",
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "enrollment_pending"


def test_pending_soldier_cannot_submit_exemption_request(client: TestClient, admin_session: Session):
    from app.db.models import ExemptionType

    node = create_node(admin_session, level="unit", name="probe_unit_exemption")
    s = create_soldier(admin_session, personal_number="7600012", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    et = ExemptionType(name="probe_exemption_type", description=None)
    admin_session.add(et)
    admin_session.commit()

    r = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(s),
        json={
            "exemption_type_id": str(et.id),
            "start_date": (date.today() + timedelta(days=1)).isoformat(),
            "end_date": None,
            "reason": "test",
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "enrollment_pending"


def test_pending_soldier_can_still_read_own_duties(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="probe_unit_read")
    s = create_soldier(admin_session, personal_number="7600013", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()

    r = client.get("/api/me/constraints", headers=auth_headers(s))
    assert r.status_code == 200
