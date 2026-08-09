from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyReserveLink,
    DutyShift,
    DutyType,
    RangeAssignment,
    RangeEvent,
    RangeType,
    SoldierRangeQualification,
)
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_node, create_range_location, create_soldier


def test_calendar_weapon_ineligible_count_is_scoped_unique_and_projects_duty_dates(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="calendar-warning-admin", role="admin")
    visible_node = create_node(admin_session, level="branch", name="calendar-warning-visible")
    other_node = create_node(admin_session, level="branch", name="calendar-warning-other")
    warned = create_soldier(
        admin_session, personal_number="calendar-warning-warned", hierarchy_node_id=visible_node.id
    )
    qualified = create_soldier(
        admin_session, personal_number="calendar-warning-qualified", hierarchy_node_id=visible_node.id
    )
    outside_scope = create_soldier(
        admin_session, personal_number="calendar-warning-outside", hierarchy_node_id=other_node.id
    )
    weapon_duty = DutyType(
        name="calendar-warning-weapon",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        required_range_type=RangeType.laser,
    )
    plain_duty = DutyType(name="calendar-warning-plain", score_per_day=Decimal("1.00"))
    location = DutyLocation(name="calendar-warning-location")
    admin_session.add_all([weapon_duty, plain_duty, location])
    admin_session.flush()

    duty_day = date.today() + timedelta(days=10)

    def add_assignment(soldier_id, duty_type, day):
        shift = DutyShift(
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            start_date=day,
            end_date=day + timedelta(days=1),
            required_count=1,
            status="active",
        )
        admin_session.add(shift)
        admin_session.flush()
        assignment = DutyAssignment(
            soldier_id=soldier_id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            duty_shift_id=shift.id,
            start_date=day,
            end_date=day + timedelta(days=1),
            status="published",
        )
        admin_session.add(assignment)

    # Two visible weapon duties for one soldier must yield one warning. A
    # non-weapon duty must not contribute, and a different subtree is hidden.
    add_assignment(warned.id, weapon_duty, duty_day)
    add_assignment(warned.id, weapon_duty, duty_day + timedelta(days=1))
    add_assignment(warned.id, plain_duty, duty_day)
    add_assignment(qualified.id, weapon_duty, duty_day)
    add_assignment(outside_scope.id, weapon_duty, duty_day)

    # This qualification is valid today but expires before the duty, so the
    # count must evaluate the scheduled duty date rather than the request date.
    admin_session.add(
        SoldierRangeQualification(
            soldier_id=qualified.id,
            range_type=RangeType.laser,
            valid_until=duty_day - timedelta(days=1),
        )
    )
    for is_reserve, is_draft in [(True, False), (False, True)]:
        event = RangeEvent(
            hierarchy_node_id=visible_node.id,
            range_type=RangeType.laser,
            date=duty_day,
            range_location_id=create_range_location(admin_session).id,
            required_count=1,
        )
        admin_session.add(event)
        admin_session.flush()
        admin_session.add(
            RangeAssignment(
                range_event_id=event.id,
                soldier_id=warned.id,
                is_reserve=is_reserve,
                is_draft=is_draft,
            )
        )
    set_setting(admin_session, "mitvachim.enabled", True, actor_id=None)
    admin_session.commit()

    response = client.get(
        "/api/calendar/weapon-ineligible/count",
        params={
            "node_id": str(visible_node.id),
            "date_from": duty_day.isoformat(),
            "date_to": (duty_day + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(admin),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"count": 2}


def test_calendar_weapon_ineligible_count_forbids_non_admin_outside_requested_node(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="calendar-count-admin", role="admin")
    visible_node = create_node(admin_session, level="branch", name="calendar-count-visible")
    outside_node = create_node(admin_session, level="branch", name="calendar-count-outside")
    outsider = create_soldier(
        admin_session,
        personal_number="calendar-count-outsider",
        role="commander",
        hierarchy_node_id=outside_node.id,
    )
    outside_node.commander_id = outsider.id
    assigned = create_soldier(
        admin_session, personal_number="calendar-count-assigned", hierarchy_node_id=visible_node.id
    )
    duty_type = DutyType(
        name="calendar-count-weapon",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        required_range_type=RangeType.laser,
    )
    location = DutyLocation(name="calendar-count-location")
    day = date.today() + timedelta(days=10)
    admin_session.add_all([duty_type, location])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=day,
        end_date=day + timedelta(days=1),
        required_count=1,
        status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=assigned.id,
            duty_type_id=duty_type.id,
            duty_location_id=location.id,
            duty_shift_id=shift.id,
            start_date=day,
            end_date=day + timedelta(days=1),
            status="published",
        )
    )
    set_setting(admin_session, "mitvachim.enabled", True, actor_id=None)
    admin_session.commit()

    response = client.get(
        "/api/calendar/weapon-ineligible/count",
        params={"node_id": str(visible_node.id), "date_from": day.isoformat(), "date_to": day.isoformat()},
        headers=auth_headers(outsider),
    )

    assert response.status_code == 403, response.text


def test_shift_detail_projects_required_range_and_assignee_eligibility(
    client: TestClient, admin_session: Session
):
    """The selected shift exposes duty-date facts, not stored assignment flags."""
    admin = create_soldier(admin_session, personal_number="detail-eligibility-admin", role="admin")
    node = create_node(admin_session, level="branch", name="detail-eligibility-node")
    uncovered = create_soldier(
        admin_session, personal_number="detail-eligibility-uncovered", hierarchy_node_id=node.id
    )
    current = create_soldier(
        admin_session, personal_number="detail-eligibility-current", hierarchy_node_id=node.id
    )
    planned = create_soldier(
        admin_session, personal_number="detail-eligibility-planned", hierarchy_node_id=node.id
    )
    duty_type = DutyType(
        name="detail-eligibility-weapon",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        required_range_type=RangeType.laser,
    )
    location = DutyLocation(name="detail-eligibility-location")
    duty_day = date.today() + timedelta(days=12)
    admin_session.add_all([duty_type, location])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=duty_day,
        end_date=duty_day + timedelta(days=1),
        required_count=3,
        status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    for soldier in (uncovered, current, planned):
        admin_session.add(
            DutyAssignment(
                soldier_id=soldier.id,
                duty_type_id=duty_type.id,
                duty_location_id=location.id,
                duty_shift_id=shift.id,
                start_date=duty_day,
                end_date=duty_day + timedelta(days=1),
                status="published",
                weapon_ineligible=False,
            )
        )
    admin_session.add(
        SoldierRangeQualification(
            soldier_id=current.id,
            range_type=RangeType.laser,
            valid_until=duty_day,
        )
    )
    range_event = RangeEvent(
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        date=duty_day - timedelta(days=4),
        range_location_id=create_range_location(admin_session).id,
        required_count=1,
    )
    admin_session.add(range_event)
    admin_session.flush()
    admin_session.add(RangeAssignment(range_event_id=range_event.id, soldier_id=planned.id))
    set_setting(admin_session, "mitvachim.enabled", True, actor_id=None)
    admin_session.commit()

    response = client.get(f"/api/calendar/shifts/{shift.id}", headers=auth_headers(admin))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["required_range_type"] == "laser"
    assignees = {assignee["soldier_id"]: assignee for assignee in body["assignees"]}
    uncovered_fact = assignees[str(uncovered.id)]["range_eligibility"]
    assert uncovered_fact == {
        "eligible": False,
        "required_range_type": "laser",
        "qualification_source": None,
        "covered_by_range_date": None,
        "projected_valid_until": None,
        "reason": "weapon_qualification",
        "duty_type_name": duty_type.name,
        "start_date": duty_day.isoformat(),
    }
    assert assignees[str(current.id)]["range_eligibility"]["qualification_source"] == "current_qualification"
    planned_fact = assignees[str(planned.id)]["range_eligibility"]
    assert planned_fact["eligible"] is True
    assert planned_fact["qualification_source"] == "planned_range"
    assert planned_fact["covered_by_range_date"] == (duty_day - timedelta(days=4)).isoformat()


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

def _mark_weapon_ineligible(session: Session, shift_id):
    assignment = session.execute(
        select(DutyAssignment).where(DutyAssignment.duty_shift_id == shift_id)
    ).scalar_one()
    assignment.weapon_ineligible = True
    assignment.weapon_ineligible_reason = "אין הכשרת נשק בתוקף לתאריך התורנות"
    session.commit()


def test_shift_detail_redacts_weapon_ineligibility_from_outside_soldier(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="8400001", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    _mark_weapon_ineligible(admin_session, shift_id)
    outsider = create_soldier(admin_session, personal_number="8400002")
    admin_session.commit()

    r = client.get(f"/api/calendar/shifts/{shift_id}", headers=auth_headers(outsider))
    assert r.status_code == 200, r.text
    assignee = next(a for a in r.json()["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["weapon_ineligible"] is False
    assert assignee["weapon_ineligible_reason"] is None
    assert assignee["range_eligibility"] is None


def test_calendar_shifts_redacts_weapon_ineligibility_from_outside_soldier(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="8400003", role="admin")
    branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    _mark_weapon_ineligible(admin_session, shift_id)
    outsider = create_soldier(admin_session, personal_number="8400004")
    admin_session.commit()

    r = client.get(
        f"/api/calendar/shifts?node_id={branch.id}&date_from=2026-11-01&date_to=2026-11-01",
        headers=auth_headers(outsider),
    )
    assert r.status_code == 200, r.text
    assignee = next(
        a for a in r.json()["shifts"][0]["assignees"] if a["soldier_id"] == str(member.id)
    )
    assert assignee["weapon_ineligible"] is False
    assert assignee["weapon_ineligible_reason"] is None


def test_shift_detail_shows_weapon_ineligibility_to_affected_soldier(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="8400005", role="admin")
    _branch, member, shift_id = _setup_shift_with_dismissal(admin_session, client, admin)
    _mark_weapon_ineligible(admin_session, shift_id)

    r = client.get(f"/api/calendar/shifts/{shift_id}", headers=auth_headers(member))
    assert r.status_code == 200, r.text
    assignee = next(a for a in r.json()["assignees"] if a["soldier_id"] == str(member.id))
    assert assignee["weapon_ineligible"] is True
    assert assignee["weapon_ineligible_reason"] == "אין הכשרת נשק בתוקף לתאריך התורנות"


def test_calendar_shifts_preserves_scoped_linked_reserve_weapon_fields(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="8400006", role="admin")
    queried_node = create_node(admin_session, level="branch", name="cal-linked-primary")
    reserve_node = create_node(admin_session, level="branch", name="cal-linked-reserve")
    primary = create_soldier(
        admin_session, personal_number="8400007", hierarchy_node_id=queried_node.id
    )
    reserve = create_soldier(
        admin_session, personal_number="8400008", hierarchy_node_id=reserve_node.id
    )
    scoped_viewer = create_soldier(
        admin_session,
        personal_number="8400009",
        role="duty_manager",
        hierarchy_node_id=reserve_node.id,
    )
    outsider = create_soldier(admin_session, personal_number="8400010")
    duty_type = DutyType(name="cal-linked-reserve", score_per_day=Decimal("1.00"))
    duty_location = DutyLocation(name="cal-linked-reserve-location")
    admin_session.add_all([duty_type, duty_location])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        required_count=1,
        status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    primary_assignment = DutyAssignment(
        soldier_id=primary.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        duty_shift_id=shift.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        status="published",
    )
    reserve_assignment = DutyAssignment(
        soldier_id=reserve.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        duty_shift_id=shift.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        status="published",
        is_reserve=True,
        weapon_ineligible=True,
        weapon_ineligible_reason="reserve weapon reason",
    )
    admin_session.add_all([primary_assignment, reserve_assignment])
    admin_session.flush()
    admin_session.add(
        DutyReserveLink(
            primary_assignment_id=primary_assignment.id,
            reserve_assignment_id=reserve_assignment.id,
            hierarchy_distance=5,
        )
    )
    admin_session.commit()

    query = (
        f"/api/calendar/shifts?node_id={queried_node.id}"
        "&date_from=2026-12-01&date_to=2026-12-01"
    )
    scoped_response = client.get(query, headers=auth_headers(scoped_viewer))
    assert scoped_response.status_code == 200, scoped_response.text
    scoped_assignee = next(
        a
        for a in scoped_response.json()["shifts"][0]["assignees"]
        if a["soldier_id"] == str(reserve.id)
    )
    assert scoped_assignee["hierarchy_path_ids"]
    assert scoped_assignee["weapon_ineligible"] is True
    assert scoped_assignee["weapon_ineligible_reason"] == "reserve weapon reason"

    outsider_response = client.get(query, headers=auth_headers(outsider))
    assert outsider_response.status_code == 200, outsider_response.text
    outsider_assignee = next(
        a
        for a in outsider_response.json()["shifts"][0]["assignees"]
        if a["soldier_id"] == str(reserve.id)
    )
    assert outsider_assignee["weapon_ineligible"] is False
    assert outsider_assignee["weapon_ineligible_reason"] is None
