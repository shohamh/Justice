from __future__ import annotations

from decimal import Decimal

from app.db.models import DutyLocation, DutyShift, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn: str):
    node = create_node(session, level="branch", name=f"n_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name=f"t_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"l_{pn}")
    session.add(dt); session.add(loc); session.flush()
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date="2027-03-01",
        end_date="2027-03-01",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, shift


def _create_job(client, dm, shift):
    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 202
    return resp.json()["id"]


def test_list_jobs_seen_false_by_default(client, admin_session):
    dm, shift = _setup(admin_session, "seen_001")
    job_id = _create_job(client, dm, shift)
    resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == job_id
    assert items[0]["seen"] is False


def test_mark_job_seen_returns_204(client, admin_session):
    dm, shift = _setup(admin_session, "seen_002")
    job_id = _create_job(client, dm, shift)
    resp = client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm))
    assert resp.status_code == 204


def test_mark_job_seen_idempotent(client, admin_session):
    dm, shift = _setup(admin_session, "seen_003")
    job_id = _create_job(client, dm, shift)
    client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm))
    resp = client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm))
    assert resp.status_code == 204


def test_mark_job_seen_reflected_in_list(client, admin_session):
    dm, shift = _setup(admin_session, "seen_004")
    job_id = _create_job(client, dm, shift)
    client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm))
    resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm))
    items = resp.json()["items"]
    assert items[0]["seen"] is True


def test_mark_all_seen_returns_204(client, admin_session):
    dm, shift = _setup(admin_session, "seen_005")
    _create_job(client, dm, shift)
    resp = client.post("/api/algorithm/jobs/mark-all-seen", headers=auth_headers(dm))
    assert resp.status_code == 204


def test_seen_is_per_user(client, admin_session):
    """One user marking a job seen does not affect another user's view."""
    node = create_node(admin_session, level="branch", name="n_seen_006")
    dm1 = create_soldier(admin_session, personal_number="seen_006a", role="duty_manager", hierarchy_node_id=node.id)
    dm2 = create_soldier(admin_session, personal_number="seen_006b", role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name="t_seen_006", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="l_seen_006")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id, start_date="2027-04-01", end_date="2027-04-01", required_count=1)
    admin_session.add(shift); admin_session.commit()

    # dm1 creates a job and marks it seen
    job_id = _create_job(client, dm1, shift)
    client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm1))

    # dm1 sees it as seen=True
    items1 = client.get("/api/algorithm/jobs", headers=auth_headers(dm1)).json()["items"]
    assert items1[0]["seen"] is True

    # dm2 creates their own job — it is not seen
    job_id2 = _create_job(client, dm2, shift)
    items2 = client.get("/api/algorithm/jobs", headers=auth_headers(dm2)).json()["items"]
    assert items2[0]["id"] == job_id2
    assert items2[0]["seen"] is False
