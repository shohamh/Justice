from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def test_commander_sees_subtree_calendar(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5700001", role="admin")
    dept = create_node(admin_session, level="department", name="dep-cal")
    branch = create_node(admin_session, level="branch", name="br-cal", parent=dept)
    cmd = create_soldier(admin_session, personal_number="5700002", role="commander")
    branch.commander_id = cmd.id
    member = create_soldier(
        admin_session, personal_number="5700003", role="soldier", hierarchy_node_id=branch.id
    )
    admin_session.commit()
    dt = DutyType(name="שמירה-cal", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="מוצב-cal")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={
            "soldier_id": str(member.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
        },
    )
    r = client.get(f"/api/calendar/unit?node_id={branch.id}", headers=auth_headers(cmd))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(row["soldier_id"] == str(member.id) and len(row["assignments"]) == 1 for row in rows)


def test_plain_soldier_forbidden_calendar(client: TestClient, admin_session: Session):
    dept = create_node(admin_session, level="department", name="dep-cal2")
    s = create_soldier(
        admin_session, personal_number="5700004", role="soldier", hierarchy_node_id=dept.id
    )
    admin_session.commit()
    r = client.get(f"/api/calendar/unit?node_id={dept.id}", headers=auth_headers(s))
    assert r.status_code == 403
