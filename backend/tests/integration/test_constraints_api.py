from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import PersonalConstraint, PersonalConstraintOverride
from app.services.holidays import holidays_in_range
from tests.helpers import auth_headers, create_node, create_soldier


def _next_holiday_free_range(span_days: int) -> tuple[date, date]:
    """First [start, start + span_days] window from today onward (inclusive
    on both ends, matching /api/me/constraints' own holiday check) that
    crosses no real IL holiday — so a "no holidays in range" test stays
    correct regardless of what day it actually runs on, instead of a
    hardcoded date that eventually rolls into the past."""
    start = date.today()
    while True:
        end = start + timedelta(days=span_days)
        if not holidays_in_range(start, end, end_inclusive=True):
            return start, end
        start += timedelta(days=1)


def test_soldier_submit_and_list(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500001")
    r = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    )
    assert r.status_code == 201, r.text
    r2 = client.get("/api/me/constraints", headers=auth_headers(s))
    assert len(r2.json()) == 1


def test_soldier_cancel_own(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500002")
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.delete(f"/api/me/constraints/{c['id']}", headers=auth_headers(s))
    assert r.status_code == 204
    r2 = client.get("/api/me/constraints", headers=auth_headers(s))
    assert len(r2.json()) == 0


def test_soldier_remaining_days(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500005")
    r = client.get("/api/me/constraints/remaining", headers=auth_headers(s))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cap_days"] == 15
    assert body["used_days"] == 0
    assert body["remaining_days"] == 15
    assert "period_start" in body and "period_end" in body


def test_commander_approves_in_subtree(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7500003", role="commander")
    b.commander_id = cmd.id
    dm = create_soldier(
        admin_session, personal_number="7500016", role="duty_manager", hierarchy_node_id=b.id
    )
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="7500004", hierarchy_node_id=b.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r1 = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(cmd), json={})
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "pending_duty_manager"
    r2 = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(dm), json={})
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "approved"


def test_constraint_out_includes_overrides(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="7500019")
    overrider = create_soldier(admin_session, personal_number="7500020", role="commander")
    constraint = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        status="approved",
    )
    admin_session.add(constraint)
    admin_session.flush()
    admin_session.add(PersonalConstraintOverride(
        personal_constraint_id=constraint.id, soldier_id=soldier.id,
        overridden_by=overrider.id, assignment_kind="duty",
        reference_id=constraint.id, reason="צורך מבצעי",
    ))
    admin_session.commit()

    resp = client.get(f"/api/soldiers/{soldier.id}/constraints", headers=auth_headers(soldier))
    assert resp.status_code == 200, resp.text
    row = next(c for c in resp.json() if c["id"] == str(constraint.id))
    assert len(row["overrides"]) == 1
    assert row["overrides"][0]["reason"] == "צורך מבצעי"
    assert row["overrides"][0]["assignment_kind"] == "duty"
    assert row["overrides"][0]["overridden_by"]["name"] == overrider.full_name


def test_commander_cannot_approve_duty_manager_step(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7500017", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="7500018", hierarchy_node_id=b.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r1 = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(cmd), json={})
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "pending_duty_manager"
    r2 = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(cmd), json={})
    assert r2.status_code == 403, r2.text

def test_commander_out_of_subtree_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="7500005", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="7500006", hierarchy_node_id=other.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(cmd), json={})
    assert r.status_code == 403


def test_soldier_cannot_approve(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500007", role="soldier")
    target = create_soldier(admin_session, personal_number="7500008")
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(s), json={})
    assert r.status_code == 403


def test_pending_count(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    dm = create_soldier(
        admin_session, personal_number="7500009", role="duty_manager", hierarchy_node_id=d.id
    )
    target = create_soldier(admin_session, personal_number="7500010", hierarchy_node_id=d.id)
    client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.get("/api/constraints/pending/count", headers=auth_headers(dm))
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_reject_requires_note(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    cmd = create_soldier(admin_session, personal_number="7500011", role="commander")
    d.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="7500012", hierarchy_node_id=d.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r = client.post(
        f"/api/constraints/{c['id']}/reject",
        headers=auth_headers(cmd),
        json={"decision_note": "לא מתאים"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_constraint_list_includes_nearest_commander_and_duty_manager(
    client: TestClient, admin_session: Session
):
    d = create_node(admin_session, level="department", name="d-nearest")
    b = create_node(admin_session, level="branch", name="b-nearest", parent=d)
    cmd = create_soldier(admin_session, personal_number="7500013", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    dm = create_soldier(
        admin_session, personal_number="7500014", role="duty_manager", hierarchy_node_id=d.id
    )
    target = create_soldier(admin_session, personal_number="7500015", hierarchy_node_id=b.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    assert c["nearest_commander"]["id"] == str(cmd.id)
    assert c["nearest_duty_manager"]["id"] == str(dm.id)
    r = client.get("/api/me/constraints", headers=auth_headers(target))
    items = r.json()
    assert len(items) == 1
    assert items[0]["nearest_commander"]["id"] == str(cmd.id)
    assert items[0]["nearest_commander"]["name"] == cmd.full_name
    assert items[0]["nearest_duty_manager"]["id"] == str(dm.id)
    assert items[0]["nearest_duty_manager"]["name"] == dm.full_name
    r2 = client.get("/api/constraints/pending", headers=auth_headers(cmd))
    pending_items = r2.json()
    assert any(i["id"] == c["id"] for i in pending_items)
    match = next(i for i in pending_items if i["id"] == c["id"])
    assert match["nearest_commander"]["id"] == str(cmd.id)
    assert match["nearest_duty_manager"]["id"] == str(dm.id)


def test_pending_list_marks_own_request_as_not_approvable(
    client: TestClient, admin_session: Session
):
    # cmd commands node b and also lives inside it — a common real setup, and
    # exactly the case forbid_self_target() guards: scope containment alone
    # would make cmd's own request look approvable to cmd.
    b = create_node(admin_session, level="branch", name="b-self-approve")
    cmd = create_soldier(
        admin_session, personal_number="7500016", role="commander", hierarchy_node_id=b.id
    )
    b.commander_id = cmd.id
    admin_session.commit()
    other = create_soldier(admin_session, personal_number="7500017", hierarchy_node_id=b.id)

    own = client.post(
        "/api/me/constraints",
        headers=auth_headers(cmd),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    others = client.post(
        "/api/me/constraints",
        headers=auth_headers(other),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()

    pending_items = client.get("/api/constraints/pending", headers=auth_headers(cmd)).json()
    own_row = next(i for i in pending_items if i["id"] == own["id"])
    others_row = next(i for i in pending_items if i["id"] == others["id"])
    assert own_row["can_approve"] is False
    assert others_row["can_approve"] is True

    # The backend must also refuse the click itself, not just hide the button.
    r = client.post(
        f"/api/constraints/{own['id']}/approve",
        headers=auth_headers(cmd),
        json={},
    )
    assert r.status_code == 403


def test_pending_list_marks_admins_own_request_as_not_approvable(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="7500018", role="admin")
    own = client.post(
        "/api/me/constraints",
        headers=auth_headers(admin),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    pending_items = client.get("/api/constraints/pending", headers=auth_headers(admin)).json()
    own_row = next(i for i in pending_items if i["id"] == own["id"])
    assert own_row["can_approve"] is False


def test_submit_response_includes_crossed_holidays(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500020")
    r = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            # Rosh Hashanah is 2026-09-12 to 2026-09-13 in the IL holiday calendar.
            "start_date": "2026-09-10",
            "end_date": "2026-09-14",
            "reason": "חופשה",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["crossed_holidays"]) == 2
    assert body["crossed_holidays"][0]["date"] == "2026-09-12"
    assert body["crossed_holidays"][1]["date"] == "2026-09-13"
    assert body["crossed_holidays"][0]["name"] == body["crossed_holidays"][1]["name"] == "ראש השנה"


def test_submit_response_has_empty_crossed_holidays_when_no_holiday_in_range(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7500021")
    start, end = _next_holiday_free_range(13)
    r = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={"start_date": start.isoformat(), "end_date": end.isoformat(), "reason": "חופשה"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["crossed_holidays"] == []
