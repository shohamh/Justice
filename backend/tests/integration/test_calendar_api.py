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


def test_calendar_shifts_returns_shift_events(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7100001", role="admin")
    dept = create_node(admin_session, level="department", name="cal-shift-dept")
    branch = create_node(admin_session, level="branch", name="cal-shift-br", parent=dept)
    s1 = create_soldier(
        admin_session, personal_number="7100002", role="soldier", hierarchy_node_id=branch.id
    )
    s2 = create_soldier(
        admin_session, personal_number="7100003", role="soldier", hierarchy_node_id=branch.id
    )
    admin_session.commit()
    dt = DutyType(name="שמירה-cs", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="מוצב-cs")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    shift_resp = client.post(
        "/api/shifts",
        headers=auth_headers(admin),
        json={
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
            "required_count": 2,
        },
    )
    assert shift_resp.status_code == 201
    shift_id = shift_resp.json()["id"]

    for sid in [s1.id, s2.id]:
        client.post(
            "/api/assignments",
            headers=auth_headers(admin),
            json={
                "soldier_id": str(sid),
                "duty_type_id": str(dt.id),
                "duty_location_id": str(loc.id),
                "start_date": "2026-11-01",
                "end_date": "2026-11-03",
                "duty_shift_id": shift_id,
            },
        )

    r = client.get(
        f"/api/calendar/shifts?node_id={branch.id}&date_from=2026-11-01&date_to=2026-11-03",
        headers=auth_headers(admin),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "shifts" in body
    assert len(body["shifts"]) == 1
    shift = body["shifts"][0]
    assert shift["id"] == shift_id
    assert len(shift["assignees"]) == 2
    assert all(not a["is_reserve"] for a in shift["assignees"])
    assert shift["required_count"] == 2
    assert shift["assigned_count"] == 2
    assert shift["fill_status"] == "full"
    assert shift["reserve_count"] == 0


def test_calendar_shifts_excludes_shift_with_no_assignees_in_node(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="7100010", role="admin")
    dept = create_node(admin_session, level="department", name="cal-empty")
    other = create_node(admin_session, level="branch", name="other-br", parent=dept)
    admin_session.commit()
    dt = DutyType(name="empty-shift", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="empty-loc")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    shift_resp = client.post(
        "/api/shifts",
        headers=auth_headers(admin),
        json={
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-11-05",
            "end_date": "2026-11-06",
            "required_count": 1,
        },
    )
    assert shift_resp.status_code == 201
    r = client.get(
        f"/api/calendar/shifts?node_id={other.id}&date_from=2026-11-05&date_to=2026-11-05",
        headers=auth_headers(admin),
    )
    assert r.status_code == 200
    assert len(r.json()["shifts"]) == 0
