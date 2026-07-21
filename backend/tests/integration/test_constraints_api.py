from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


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
    r = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(cmd), json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


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
    dm = create_soldier(admin_session, personal_number="7500009", role="duty_manager", hierarchy_node_id=d.id)
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
