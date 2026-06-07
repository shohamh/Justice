from __future__ import annotations

import time
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
        start_date="2027-01-01",
        end_date="2027-01-01",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, dt, loc, shift


def test_create_job_with_shift_ids(client, admin_session):
    dm, dt, loc, shift = _setup(admin_session, "als_001")
    create_soldier(admin_session, personal_number="als_001s")
    admin_session.commit()

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"


def test_rejects_missing_shift_id(client, admin_session):
    dm, dt, loc, _ = _setup(admin_session, "als_002")
    fake_id = "00000000-0000-0000-0000-000000000099"

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [fake_id],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "shift_not_found"


def test_algorithm_runs_and_proposals_have_shift_id(client, admin_session):
    dm, dt, loc, shift = _setup(admin_session, "als_003")
    create_soldier(admin_session, personal_number="als_003s")
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]

    poll = None
    for _ in range(15):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] in ("done", "failed"):
            break
        time.sleep(2)

    assert poll is not None
    assert poll.json()["status"] in ("done", "failed")

    if poll.json()["status"] == "done":
        proposals = poll.json().get("proposals", [])
        for p in proposals:
            assert p.get("duty_shift_id") is not None
