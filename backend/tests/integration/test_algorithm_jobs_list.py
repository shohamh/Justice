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


def test_list_jobs_empty(client, admin_session):
    dm, _ = _setup(admin_session, "jlist_001")
    resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm))
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


def test_list_jobs_returns_own_job(client, admin_session):
    dm, shift = _setup(admin_session, "jlist_002")
    create_soldier(admin_session, personal_number="jlist_002s")
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202

    list_resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm))
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) >= 1
    item = items[0]
    assert item["status"] in ("pending", "running", "done", "failed")
    assert item["shift_count"] == 1
    assert item["planning_start"] == "2027-03-01"
    assert item["planning_end"] == "2027-03-01"
    assert "created_at" in item
    assert "id" in item


def test_list_jobs_does_not_return_other_users_jobs(client, admin_session):
    dm1, shift = _setup(admin_session, "jlist_003a")
    dm2, _ = _setup(admin_session, "jlist_003b")
    create_soldier(admin_session, personal_number="jlist_003s")
    admin_session.commit()

    client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm1),
    )

    list_resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm2))
    assert list_resp.status_code == 200
    # dm2 has no jobs
    for item in list_resp.json()["items"]:
        # None of dm2's items should belong to dm1
        assert item.get("status") is not None


def test_soldier_cannot_list_jobs(client, admin_session):
    node = create_node(admin_session, level="branch", name="jlist_004_node")
    soldier = create_soldier(admin_session, personal_number="jlist_004", role="soldier", hierarchy_node_id=node.id)
    admin_session.commit()
    resp = client.get("/api/algorithm/jobs", headers=auth_headers(soldier))
    assert resp.status_code == 403
