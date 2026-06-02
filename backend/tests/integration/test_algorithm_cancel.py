from __future__ import annotations

import time
import uuid
from datetime import date
from decimal import Decimal

from app.db.models import AlgorithmJob, DutyLocation, DutyShift, DutyType
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
        start_date="2028-06-01",
        end_date="2028-06-01",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, shift


def _insert_pending_job(session, dm, shift_id: str) -> AlgorithmJob:
    """Insert a job directly in 'pending' status (bypassing the background task)."""
    job = AlgorithmJob(
        planning_start=date(2028, 6, 1),
        planning_end=date(2028, 6, 1),
        shift_ids=[shift_id],
        settings_json={"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 60},
        mode="shadow",
        created_by=dm.id,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_cancel_pending_job_sets_failed_and_finished_at(client, admin_session):
    """Cancel a pending job via DELETE — DB status must become 'failed' with error_message and finished_at set."""
    dm, shift = _setup(admin_session, "cancel_001")
    create_soldier(admin_session, personal_number="cancel_001s")
    admin_session.commit()

    # Insert a pending job directly (background task never starts, avoids race condition in TestClient)
    job = _insert_pending_job(admin_session, dm, str(shift.id))
    job_id = str(job.id)

    cancel_resp = client.delete(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
    assert cancel_resp.status_code == 204

    admin_session.expire_all()
    job = admin_session.get(AlgorithmJob, job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.error_message == "cancelled_by_user"
    assert job.finished_at is not None


def test_cancel_returns_409_for_done_job(client, admin_session):
    dm, shift = _setup(admin_session, "cancel_002")
    create_soldier(admin_session, personal_number="cancel_002s")
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    # TestClient runs background tasks synchronously so the job is already done/failed here
    job_id = create_resp.json()["id"]

    cancel_resp = client.delete(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
    assert cancel_resp.status_code == 409
    assert cancel_resp.json()["detail"] == "not_cancellable"
