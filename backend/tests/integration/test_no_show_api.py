from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def _seed_past_assignment(session, *, personal_number):
    from app.db.models import DutyAssignment, DutyLocation, DutyType

    dt = DutyType(name=f"dt_api_{personal_number}", score_per_day=1)
    loc = DutyLocation(name=f"loc_api_{personal_number}")
    session.add_all([dt, loc])
    session.flush()
    assignment = DutyAssignment(
        soldier_id=None, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=5), end_date=date.today() - timedelta(days=4),
        status="published",
    )
    return dt, loc, assignment


def test_duty_manager_marks_no_show(client: TestClient, admin_session: Session):
    from app.db.models import DutyAssignment, DutyLocation, DutyType

    node = create_node(admin_session, level="unit", name="ns-api-unit")
    dm = create_soldier(admin_session, personal_number="ns_api_dm1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ns_api_s1", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_ns_api", score_per_day=1)
    loc = DutyLocation(name="loc_ns_api")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=5), end_date=date.today() - timedelta(days=4),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.post(
        "/api/no-shows",
        headers=auth_headers(dm),
        json={"duty_assignment_id": str(assignment.id), "note": "לא הגיע"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["soldier_id"] == str(soldier.id)
    assert body["score_adjustment_id"] is not None

    r2 = client.get(f"/api/no-shows/soldiers/{soldier.id}", headers=auth_headers(dm))
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_soldier_cannot_mark_no_show(client: TestClient, admin_session: Session):
    from app.db.models import DutyAssignment, DutyLocation, DutyType

    node = create_node(admin_session, level="unit", name="ns-api-unit2")
    plain_soldier = create_soldier(admin_session, personal_number="ns_api_s2", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="ns_api_s3", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_ns_api2", score_per_day=1)
    loc = DutyLocation(name="loc_ns_api2")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=target.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=5), end_date=date.today() - timedelta(days=4),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.post(
        "/api/no-shows",
        headers=auth_headers(plain_soldier),
        json={"duty_assignment_id": str(assignment.id), "note": "לא הגיע"},
    )
    assert r.status_code == 403
