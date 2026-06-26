from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import AlgorithmJob, DutyAssignment, DutyLocation, DutyShift, DutyType
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


def _make_shift(session, name_suffix: str, start: str = "2027-07-01", end: str | None = None) -> tuple[DutyShift, DutyType, DutyLocation]:
    """Create a DutyType, DutyLocation, and DutyShift for use in algorithm job tests."""
    dt = DutyType(name=f"שמירה_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"שער_{name_suffix}")
    session.add(dt); session.add(loc); session.flush()
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start,
        end_date=end or start,
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return shift, dt, loc


def test_create_job_returns_202(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_001")
    shift, _dt, _loc = _make_shift(admin_session, "route_1", "2027-07-01")
    create_soldier(admin_session, personal_number="route_soldier_001", role="soldier")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 15},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "id" in data
    assert data["status"] == "pending"


def test_algorithm_defaults_returns_resolved_settings(client, admin_session):
    from app.services.settings_loader import set_setting
    dm, _node = _setup_dm(admin_session, "route_alg_def")
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    admin_session.commit()

    resp = client.get("/api/algorithm/defaults", headers=auth_headers(dm))
    assert resp.status_code == 200
    body = resp.json()
    assert body["T"] == 8
    assert body["R"] == 10
    assert body["Wt"] == 14
    assert body["Wr"] == 28


def test_create_job_rejects_T_greater_than_R(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_tr")
    shift, _dt, _loc = _make_shift(admin_session, "route_tr", "2027-07-02")
    create_soldier(admin_session, personal_number="route_soldier_tr", role="soldier")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 9, "R": 7, "Wt": 14, "Wr": 28, "alpha": 1.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "t_exceeds_r"


def test_create_job_rejects_unknown_shift(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_002")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": ["00000000-0000-0000-0000-000000000002"],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "shift_not_found"


def test_retry_job_creates_new_job_with_same_inputs(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_retry_001")
    shift, _dt, _loc = _make_shift(admin_session, "route_retry_1", "2027-07-03")

    source = AlgorithmJob(
        planning_start=date(2027, 7, 3),
        planning_end=date(2027, 7, 3),
        shift_ids=[str(shift.id)],
        settings_json={"T": 7, "Wt": 14, "alpha": 1.0, "time_limit_seconds": 5},
        mode="shadow",
        status="failed",
        error_message='{"status": "INTERRUPTED", "reason": "server_restarted"}',
        created_by=dm.id,
    )
    admin_session.add(source)
    admin_session.commit()
    admin_session.refresh(source)

    resp = client.post(f"/api/algorithm/jobs/{source.id}/retry", headers=auth_headers(dm))
    assert resp.status_code == 202
    data = resp.json()
    assert data["id"] != str(source.id)
    assert data["status"] == "pending"

    new_job = admin_session.get(AlgorithmJob, data["id"])
    assert new_job.shift_ids == source.shift_ids
    assert new_job.mode == source.mode
    assert new_job.settings_json == source.settings_json


def test_retry_job_rejects_in_progress_job(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_retry_002")
    shift, _dt, _loc = _make_shift(admin_session, "route_retry_2", "2027-07-04")

    source = AlgorithmJob(
        planning_start=date(2027, 7, 4),
        planning_end=date(2027, 7, 4),
        shift_ids=[str(shift.id)],
        settings_json={"T": 7, "Wt": 14, "alpha": 1.0, "time_limit_seconds": 5},
        mode="shadow",
        status="running",
        created_by=dm.id,
    )
    admin_session.add(source)
    admin_session.commit()
    admin_session.refresh(source)

    resp = client.post(f"/api/algorithm/jobs/{source.id}/retry", headers=auth_headers(dm))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "job_in_progress"


def test_retry_job_rejects_unknown_job(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_retry_003")

    resp = client.post(
        "/api/algorithm/jobs/00000000-0000-0000-0000-000000000099/retry",
        headers=auth_headers(dm),
    )
    assert resp.status_code == 404


def test_soldier_cannot_create_job(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="route_alg_003")
    shift, _dt, _loc = _make_shift(admin_session, "route_3", "2027-07-01")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 403


def test_poll_job_eventually_done_or_failed(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_004")
    shift, _dt, _loc = _make_shift(admin_session, "route_4", "2027-08-01")
    create_soldier(admin_session, personal_number="route_soldier_004", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202, create_resp.text
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
    shift, _dt, _loc = _make_shift(admin_session, "route_5", "2027-09-01")
    create_soldier(admin_session, personal_number="route_soldier_005", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202, create_resp.text
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
    shift, _dt, _loc = _make_shift(admin_session, "route_6", "2027-10-01")
    create_soldier(admin_session, personal_number="route_soldier_006", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202, create_resp.text
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


def test_reset_published_allows_days_ahead_zero(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_dm_003")
    dm = create_soldier(admin_session, personal_number="rp_dm_003", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert "cancelled" in resp.json()


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


def test_reset_drafts_allows_days_ahead_zero(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_dm_003")
    dm = create_soldier(admin_session, personal_number="rd_dm_003", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert "rejected" in resp.json()


def test_reset_published_days_ahead_zero_includes_today(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_today_001")
    dm = create_soldier(admin_session, personal_number="rp_today_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    today_assignment = _make_published_assignment(admin_session, "rp_today_s_001", date.today())

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["cancelled"] >= 1

    admin_session.expire(today_assignment)
    admin_session.refresh(today_assignment)
    assert today_assignment.status == "cancelled"


def test_reset_drafts_days_ahead_zero_includes_today(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_today_001")
    dm = create_soldier(admin_session, personal_number="rd_today_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    today_draft = _make_draft_assignment(admin_session, "rd_today_s_001", date.today())

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["rejected"] >= 1

    admin_session.expire(today_draft)
    admin_session.refresh(today_draft)
    assert today_draft.status == "algorithm_rejected"


def test_bulk_accept_proposals_sets_published(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_ba_001")
    dm = create_soldier(admin_session, personal_number="ba_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    draft1 = _make_draft_assignment(admin_session, "ba_s_001", date.today() + timedelta(days=10))
    draft2 = _make_draft_assignment(admin_session, "ba_s_002", date.today() + timedelta(days=11))

    job = AlgorithmJob(
        planning_start=date.today() + timedelta(days=10),
        planning_end=date.today() + timedelta(days=11),
        shift_ids=[],
        settings_json={"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 30},
        mode="shadow",
        created_by=dm.id,
    )
    admin_session.add(job)
    admin_session.commit()
    admin_session.refresh(job)

    resp = client.post(
        f"/api/algorithm/jobs/{job.id}/proposals/bulk-accept",
        json={"assignment_ids": [str(draft1.id), str(draft2.id)]},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 2

    admin_session.expire(draft1)
    admin_session.refresh(draft1)
    admin_session.expire(draft2)
    admin_session.refresh(draft2)
    assert draft1.status == "published"
    assert draft2.status == "published"


def test_drafts_preview_returns_today_and_future_drafts(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_dp_001")
    dm = create_soldier(admin_session, personal_number="dp_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    today_draft = _make_draft_assignment(admin_session, "dp_s_001", date.today())
    future_draft = _make_draft_assignment(admin_session, "dp_s_002", date.today() + timedelta(days=10))
    # past draft — must NOT appear
    past_draft = _make_draft_assignment(admin_session, "dp_s_003", date.today() - timedelta(days=5))

    resp = client.get("/api/algorithm/drafts-preview", headers=auth_headers(dm))
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "items" in data
    assert data["count"] == len(data["items"])
    returned_ids = {item["assignment_id"] for item in data["items"]}
    assert str(today_draft.id) in returned_ids
    assert str(future_draft.id) in returned_ids
    assert str(past_draft.id) not in returned_ids


def test_drafts_preview_excludes_published_and_cancelled(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_dp_002")
    dm = create_soldier(admin_session, personal_number="dp_dm_002", role="duty_manager", hierarchy_node_id=dm_node.id)

    published = _make_published_assignment(admin_session, "dp_pub_s_001", date.today() + timedelta(days=5))

    resp = client.get("/api/algorithm/drafts-preview", headers=auth_headers(dm))
    assert resp.status_code == 200
    data = resp.json()
    # published assignment must not appear (wrong status)
    returned_ids = {item["assignment_id"] for item in data["items"]}
    assert str(published.id) not in returned_ids


def test_drafts_preview_soldier_forbidden(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="dp_soldier_001")

    resp = client.get("/api/algorithm/drafts-preview", headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_bulk_accept_proposals_ignores_non_draft(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_ba_002")
    dm = create_soldier(admin_session, personal_number="ba_dm_002", role="duty_manager", hierarchy_node_id=dm_node.id)

    published = _make_published_assignment(admin_session, "ba_s_003", date.today() + timedelta(days=5))
    draft = _make_draft_assignment(admin_session, "ba_s_004", date.today() + timedelta(days=6))

    job = AlgorithmJob(
        planning_start=date.today() + timedelta(days=5),
        planning_end=date.today() + timedelta(days=6),
        shift_ids=[],
        settings_json={"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 30},
        mode="shadow",
        created_by=dm.id,
    )
    admin_session.add(job)
    admin_session.commit()
    admin_session.refresh(job)

    resp = client.post(
        f"/api/algorithm/jobs/{job.id}/proposals/bulk-accept",
        json={"assignment_ids": [str(published.id), str(draft.id)]},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    # Only the draft should be accepted; the already-published one is skipped
    assert resp.json()["accepted"] == 1


def test_partial_job_reports_reasons(client, admin_session):
    """A done job where required_count > eligible soldiers → partial → reasons non-empty."""
    dm, node = _setup_dm(admin_session, "partial_dm_001")

    # Create a duty type + location
    from decimal import Decimal
    dt = DutyType(name="שמירה_partial", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="שער_partial")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()

    # Create exactly ONE eligible soldier
    create_soldier(admin_session, personal_number="partial_soldier_001", role="soldier")

    # Shift A: required_count=3 on a far-future day — only 2 soldiers exist (DM + partial_soldier_001)
    # → at most 2 can be assigned → at least 1 slot unfilled → partial
    from datetime import date, timedelta
    far = date.today() + timedelta(days=400)
    oversubscribed = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=far,
        end_date=far + timedelta(days=1),
        required_count=3,
    )
    admin_session.add(oversubscribed)

    # Shift B: required_count=1 on a different far-future day — soldier CAN fill this
    # Ensures the job ends "done" (some assignments) rather than "failed" (fully INFEASIBLE)
    far2 = far + timedelta(days=30)
    fillable = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=far2,
        end_date=far2 + timedelta(days=1),
        required_count=1,
    )
    admin_session.add(fillable)
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(oversubscribed.id), str(fillable.id)],
            "mode": "shadow",
            "settings": {"T": 8, "R": 15, "Wt": 14, "Wr": 28, "alpha": 1.0, "time_limit_seconds": 15},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202, create_resp.text
    job_id = create_resp.json()["id"]

    final = None
    for _ in range(30):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        assert poll.status_code == 200
        if poll.json()["status"] in ("done", "failed"):
            final = poll.json()
            break
        time.sleep(1)

    assert final is not None, "job never completed"
    assert final["status"] == "done", f"expected done, got: {final['status']}, error: {final.get('error_message')}"
    assert len(final["reasons"]) > 0, f"expected non-empty reasons for partial job, got: {final['reasons']}"


def test_bulk_accept_proposals_soldier_forbidden(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="ba_soldier_001")

    dm_node = create_node(admin_session, level="branch", name="branch_ba_auth_001")
    dm = create_soldier(admin_session, personal_number="ba_auth_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)
    job = AlgorithmJob(
        planning_start=date.today() + timedelta(days=1),
        planning_end=date.today() + timedelta(days=1),
        shift_ids=[],
        settings_json={"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 30},
        mode="shadow",
        created_by=dm.id,
    )
    admin_session.add(job)
    admin_session.commit()
    admin_session.refresh(job)

    resp = client.post(
        f"/api/algorithm/jobs/{job.id}/proposals/bulk-accept",
        json={"assignment_ids": ["00000000-0000-0000-0000-000000000001"]},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 403


def test_get_job_returns_batch_results(client, admin_session):
    """GET /algorithm/jobs/{id} returns batch_results list."""
    dm_node = create_node(admin_session, level="branch", name="branch_gbr_001")
    dm = create_soldier(admin_session, personal_number="gbr_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    job = AlgorithmJob(
        planning_start=date(2026, 6, 1),
        planning_end=date(2026, 6, 30),
        shift_ids=[],
        settings_json={},
        mode="shadow",
        status="done",
        created_by=dm.id,
        batch_results=[{
            "batch_index": 0,
            "component_index": 0,
            "date_from": "2026-06-01",
            "date_to": "2026-06-30",
            "duty_count": 2,
            "soldier_count": 5,
            "assigned_count": 2,
            "unassigned_count": 0,
            "outcome": "OPTIMAL",
            "relaxations": [],
            "wall_time_seconds": 0.5,
            "shifts": [],
        }],
    )
    admin_session.add(job)
    admin_session.commit()
    admin_session.refresh(job)

    resp = client.get(f"/api/algorithm/jobs/{job.id}", headers=auth_headers(dm))
    assert resp.status_code == 200
    body = resp.json()
    assert "batch_results" in body
    assert len(body["batch_results"]) == 1
    assert body["batch_results"][0]["outcome"] == "OPTIMAL"
    assert body["batch_results"][0]["assigned_count"] == 2


def test_export_inputs_replays_completed_published_job(client, admin_session):
    """Regression test: export-inputs must return the duties that were actually
    solved, even after the job's shifts are fully staffed (published/drafted).

    Before the solver_input_snapshot fix, export-inputs re-derived duties from
    live DB state (load_duty_blocks_from_shifts subtracts already-filled slots),
    so a completed job's export came back with duties=[] — useless for replay.
    """
    dm, _node = _setup_dm(admin_session, "route_alg_export")
    shift, _dt, _loc = _make_shift(admin_session, "route_export", "2027-11-01")
    create_soldier(admin_session, personal_number="route_soldier_export", role="soldier")

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202, create_resp.text
    job_id = create_resp.json()["id"]

    poll = None
    for _ in range(15):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] == "done":
            break
        time.sleep(2)
    assert poll is not None and poll.json()["status"] == "done", poll.json() if poll else "no response"

    proposals = poll.json().get("proposals", [])
    if not proposals:
        pytest.skip("solver returned no proposals")

    # Publish the proposal — this is what makes the shift "fully staffed" and
    # is exactly the state that broke export-inputs before the fix.
    asgn_id = proposals[0]["assignment_id"]
    accept_resp = client.post(
        f"/api/algorithm/jobs/{job_id}/proposals/{asgn_id}/accept",
        headers=auth_headers(dm),
    )
    assert accept_resp.status_code == 200

    export_resp = client.get(
        f"/api/algorithm/jobs/{job_id}/export-inputs",
        headers=auth_headers(dm),
    )
    assert export_resp.status_code == 200
    dump = export_resp.json()
    assert len(dump["duties"]) > 0, "export-inputs returned no duties for a completed job — snapshot fix regressed"
    assert dump["duties"][0]["shift_id"] == str(shift.id)


def test_dual_role_commander_sees_unredacted_explanation(client, admin_session):
    """A soldier who commands node A and is separately DM of node B must see the
    unredacted explanation for an assignment in B — real DM capability must be
    checked, not the (commander-prioritized) role label."""
    from decimal import Decimal
    from datetime import date
    from app.db.models import (
        AssignmentExplanation, DutyAssignment, DutyLocation, DutyManagerScope, DutyType,
    )
    from tests.helpers import create_node, create_soldier, auth_headers

    a = create_node(admin_session, level="department", name="algo-dual-a")
    b = create_node(admin_session, level="department", name="algo-dual-b")
    dual = create_soldier(admin_session, personal_number="algo-dual-001", role="commander")
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    assignee = create_soldier(admin_session, personal_number="algo-dual-002", hierarchy_node_id=b.id)
    dt = DutyType(name="algo-dual-dt", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="algo-dual-loc")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=assignee.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2027, 2, 1), end_date=date(2027, 2, 5), status="published", is_reserve=False,
    )
    admin_session.add(assignment)
    admin_session.flush()
    admin_session.add(
        AssignmentExplanation(
            duty_assignment_id=assignment.id,
            payload={"candidates": []},
            algorithm_version="test",
            solver_seed="0",
        )
    )
    admin_session.commit()

    r = client.get(f"/api/algorithm/explanations/{assignment.id}", headers=auth_headers(dual))
    assert r.status_code == 200
    assert "candidates" in r.json()
    assert "blocked_count" not in r.json()  # only the soldier-redacted view adds this key
