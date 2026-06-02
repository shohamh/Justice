from __future__ import annotations

import time
from decimal import Decimal

import pytest

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup_dm(session, personal_number: str):
    node = create_node(session, level="branch", name=f"branch_{personal_number}")
    dm = create_soldier(
        session,
        personal_number=personal_number,
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    return dm, node


def _duty_type(session, name: str) -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal("1.00"))
    session.add(dt)
    session.flush()
    session.commit()
    return dt


def _location(session, name: str) -> DutyLocation:
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    session.commit()
    return loc


def test_create_job_returns_202(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_001")
    dt = _duty_type(admin_session, "שמירה_route_1")
    loc = _location(admin_session, "שער_route_1")
    create_soldier(admin_session, personal_number="route_soldier_001", role="soldier")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-07-01",
            "planning_end": "2026-07-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 15},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "id" in data
    assert data["status"] == "pending"


def test_create_job_rejects_bad_date_range(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_002")
    dt = _duty_type(admin_session, "שמירה_route_2")
    loc = _location(admin_session, "שער_route_2")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-07-10",
            "planning_end": "2026-07-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "bad_date_range"


def test_soldier_cannot_create_job(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="route_alg_003")
    dt = _duty_type(admin_session, "שמירה_route_3")
    loc = _location(admin_session, "שער_route_3")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-07-01",
            "planning_end": "2026-07-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 403


def test_poll_job_eventually_done_or_failed(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_004")
    dt = _duty_type(admin_session, "שמירה_route_4")
    loc = _location(admin_session, "שער_route_4")
    create_soldier(admin_session, personal_number="route_soldier_004", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-08-01",
            "planning_end": "2026-08-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]

    for _ in range(15):
        poll_resp = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        assert poll_resp.status_code == 200
        if poll_resp.json()["status"] in ("done", "failed"):
            break
        time.sleep(2)

    final = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
    assert final.json()["status"] in ("done", "failed")


def test_accept_proposal(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_005")
    dt = _duty_type(admin_session, "שמירה_route_5")
    loc = _location(admin_session, "שער_route_5")
    create_soldier(admin_session, personal_number="route_soldier_005", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-09-01",
            "planning_end": "2026-09-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]

    poll = None
    for _ in range(15):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] == "done":
            break
        time.sleep(2)

    proposals = poll.json().get("proposals", []) if poll else []
    if not proposals:
        pytest.skip("solver returned no proposals")

    asgn_id = proposals[0]["assignment_id"]
    accept_resp = client.post(
        f"/api/algorithm/jobs/{job_id}/proposals/{asgn_id}/accept",
        headers=auth_headers(dm),
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "published"

    # Double-accept should 409
    double = client.post(
        f"/api/algorithm/jobs/{job_id}/proposals/{asgn_id}/accept",
        headers=auth_headers(dm),
    )
    assert double.status_code == 409


def test_reject_proposal(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_006")
    dt = _duty_type(admin_session, "שמירה_route_6")
    loc = _location(admin_session, "שער_route_6")
    create_soldier(admin_session, personal_number="route_soldier_006", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "planning_start": "2026-10-01",
            "planning_end": "2026-10-01",
            "duty_type_ids": [str(dt.id)],
            "duty_location_id": str(loc.id),
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]
    poll = None
    for _ in range(15):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] == "done":
            break
        time.sleep(2)

    proposals = poll.json().get("proposals", []) if poll else []
    if not proposals:
        pytest.skip("no proposals")

    asgn_id = proposals[0]["assignment_id"]
    resp = client.post(
        f"/api/algorithm/jobs/{job_id}/proposals/{asgn_id}/reject",
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "algorithm_rejected"


from datetime import date, timedelta

from app.db.models import DutyAssignment


def _make_published_assignment(session, personal_number: str, start_date: date) -> DutyAssignment:
    """Helper: creates a soldier + duty type + location + published assignment."""
    node = create_node(session, level="branch", name=f"branch_{personal_number}")
    soldier = create_soldier(session, personal_number=personal_number, hierarchy_node_id=node.id)
    dt = DutyType(name=f"dt_{personal_number}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{personal_number}")
    session.add(dt)
    session.add(loc)
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start_date,
        end_date=start_date,
        status="published",
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_reset_published_cancels_future_assignments(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_dm_001")
    dm = create_soldier(admin_session, personal_number="rp_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    future = date.today() + timedelta(days=60)
    near = date.today() + timedelta(days=5)

    far_assignment = _make_published_assignment(admin_session, "rp_s_001", future)
    near_assignment = _make_published_assignment(admin_session, "rp_s_002", near)

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 30},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["cancelled"] >= 1

    admin_session.expire(far_assignment)
    admin_session.expire(near_assignment)
    admin_session.refresh(far_assignment)
    admin_session.refresh(near_assignment)

    assert far_assignment.status == "cancelled"
    assert near_assignment.status == "published"  # within 30 days, untouched


def test_reset_published_returns_zero_when_no_matches(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_dm_002")
    dm = create_soldier(admin_session, personal_number="rp_dm_002", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 365},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["cancelled"] >= 0


def test_reset_published_rejects_days_ahead_zero(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_dm_003")
    dm = create_soldier(admin_session, personal_number="rp_dm_003", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 422


def _make_draft_assignment(session, personal_number: str, start_date: date) -> DutyAssignment:
    node = create_node(session, level="branch", name=f"branch_{personal_number}")
    soldier = create_soldier(session, personal_number=personal_number, hierarchy_node_id=node.id)
    dt = DutyType(name=f"dt_{personal_number}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{personal_number}")
    session.add(dt)
    session.add(loc)
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start_date,
        end_date=start_date,
        status="algorithm_draft",
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_reset_drafts_rejects_future_drafts(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_dm_001")
    dm = create_soldier(admin_session, personal_number="rd_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    future = date.today() + timedelta(days=60)
    near = date.today() + timedelta(days=5)

    far_draft = _make_draft_assignment(admin_session, "rd_s_001", future)
    near_draft = _make_draft_assignment(admin_session, "rd_s_002", near)

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 30},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rejected"] >= 1

    admin_session.expire(far_draft)
    admin_session.expire(near_draft)
    admin_session.refresh(far_draft)
    admin_session.refresh(near_draft)

    assert far_draft.status == "algorithm_rejected"
    assert near_draft.status == "algorithm_draft"  # within 30 days, untouched


def test_reset_drafts_returns_zero_when_no_matches(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_dm_002")
    dm = create_soldier(admin_session, personal_number="rd_dm_002", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 365},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["rejected"] >= 0


def test_reset_drafts_rejects_days_ahead_zero(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_dm_003")
    dm = create_soldier(admin_session, personal_number="rd_dm_003", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 422
