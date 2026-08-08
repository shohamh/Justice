from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyShift, DutyType, RangeType
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


def _create_dismissal(session, assignment_id, reason="בעיה רפואית"):
    d = DutyDismissal(
        duty_assignment_id=assignment_id,
        dismissed_from=date(2026, 11, 1),
        dismissed_to=date(2026, 11, 2),
        reason=reason,
    )
    session.add(d)
    session.commit()
    return d


def _setup_shift_with_dismissal(admin_session, client, admin):
    dept = create_node(admin_session, level="department", name="dep-reason")
    branch = create_node(admin_session, level="branch", name="br-reason", parent=dept)
    member = create_soldier(
        admin_session, personal_number="8200001", role="soldier", hierarchy_node_id=branch.id
    )
    admin_session.commit()
    dt = DutyType(name="שמירה-reason", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="מוצב-reason")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    shift_resp = client.post(
        "/api/shifts",
        headers=auth_headers(admin),
        json={
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
            "required_count": 1,
        },
    )
    assert shift_resp.status_code == 201, shift_resp.text
    shift_id = shift_resp.json()["id"]
    assign_resp = client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={
            "soldier_id": str(member.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
            "duty_shift_id": shift_id,
        },
    )
    assert assign_resp.status_code == 201, assign_resp.text
    assignment_id = assign_resp.json()["id"]
    _create_dismissal(admin_session, assignment_id)
    return branch, member, shift_id


def test_shift_detail_hides_reason_from_outside_soldier(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8200002", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    outsider = create_soldier(admin_session, personal_number="8200003", role="soldier")
    admin_session.commit()

    r = client.get(f"/api/calendar/shifts/{shift_id}", headers=auth_headers(outsider))
    assert r.status_code == 200, r.text
    assignee = next(a for a in r.json()["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] is None


def test_shift_detail_shows_reason_to_affected_soldier(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8200004", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)

    r = client.get(f"/api/calendar/shifts/{shift_id}", headers=auth_headers(member))
    assert r.status_code == 200, r.text
    assignee = next(a for a in r.json()["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] == "בעיה רפואית"


def test_shift_detail_shows_reason_to_commander_in_scope(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8200005", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    cmd = create_soldier(admin_session, personal_number="8200006", role="commander")
    branch.commander_id = cmd.id
    admin_session.commit()

    r = client.get(f"/api/calendar/shifts/{shift_id}", headers=auth_headers(cmd))
    assert r.status_code == 200, r.text
    assignee = next(a for a in r.json()["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] == "בעיה רפואית"


def test_calendar_shifts_hides_reason_from_outside_soldier(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8300002", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    outsider = create_soldier(admin_session, personal_number="8300003", role="soldier")
    admin_session.commit()

    r = client.get(
        f"/api/calendar/shifts?node_id={branch.id}&date_from=2026-11-01&date_to=2026-11-01",
        headers=auth_headers(outsider),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["shifts"]) == 1
    assignee = next(a for a in body["shifts"][0]["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] is None


def test_calendar_shifts_shows_reason_to_affected_soldier(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8300004", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)

    r = client.get(
        f"/api/calendar/shifts?node_id={branch.id}&date_from=2026-11-01&date_to=2026-11-01",
        headers=auth_headers(member),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["shifts"]) == 1
    assignee = next(a for a in body["shifts"][0]["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] == "בעיה רפואית"


def test_calendar_shifts_shows_reason_to_commander_in_scope(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="8300005", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    cmd = create_soldier(admin_session, personal_number="8300006", role="commander")
    branch.commander_id = cmd.id
    admin_session.commit()

    r = client.get(
        f"/api/calendar/shifts?node_id={branch.id}&date_from=2026-11-01&date_to=2026-11-01",
        headers=auth_headers(cmd),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["shifts"]) == 1
    assignee = next(a for a in body["shifts"][0]["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["dismissals"][0]["reason"] == "בעיה רפואית"


def test_calendar_shift_assignee_includes_weapon_ineligible_flag(client: TestClient, admin_session: Session):
    from datetime import timedelta

    node = create_node(admin_session, level="branch", name="cal-node-1")
    dm = create_soldier(admin_session, personal_number="cal-dm-1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="cal-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="cal-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    loc = DutyLocation(name="cal-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=1, status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        status="published",
        weapon_ineligible=True, weapon_ineligible_reason="אין הכשרת נשק בתוקף לתאריך התורנות",
    ))
    admin_session.commit()

    r = client.get(
        f"/api/calendar/shifts?node_id={node.id}&date_from={date.today().isoformat()}&date_to={(date.today()+timedelta(days=30)).isoformat()}",
        headers=auth_headers(dm),
    )
    assert r.status_code == 200
    row = next(s for s in r.json()["shifts"] if s["id"] == str(shift.id))
    assignee = next(a for a in row["assignees"] if a["soldier_id"] == str(soldier.id))
    assert assignee["weapon_ineligible"] is True
    assert assignee["weapon_ineligible_reason"] == "אין הכשרת נשק בתוקף לתאריך התורנות"
