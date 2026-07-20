from __future__ import annotations

import time
import uuid
from datetime import date
from decimal import Decimal

from app.db.models import (
    AlgorithmJob,
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    ExemptionType,
    Notification,
    NotificationType,
    SoldierExemption,
)
from app.services.algorithm_bridge import run_algorithm_job
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
        start_date="2027-04-01",
        end_date="2027-04-02",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, shift


def test_notification_created_when_job_completes(client, admin_session):
    dm, shift = _setup(admin_session, "alg_notif_001")
    create_soldier(admin_session, personal_number="alg_notif_001s")
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
    assert create_resp.status_code == 202
    job_id = create_resp.json()["id"]

    # Poll until done or failed
    poll = None
    for _ in range(20):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] in ("done", "failed"):
            break
        time.sleep(2)

    final_status = poll.json()["status"]
    assert final_status in ("done", "failed")

    # Check notification was created for the dm
    admin_session.expire_all()
    notif = admin_session.query(Notification).filter(
        Notification.soldier_id == dm.id,
        Notification.reference_type == "algorithm_job",
    ).first()

    assert notif is not None
    assert str(notif.reference_id) == job_id
    if final_status == "done":
        assert notif.type == NotificationType.algorithm_job_done
        assert "הצעות" in notif.title
    else:
        assert notif.type == NotificationType.algorithm_job_failed


def test_nothing_to_assign_notifies_creator(client, admin_session):
    """When every selected shift resolves to zero unfilled slots, the job
    finishes cleanly (status=done, NOTHING_TO_ASSIGN) but must still notify
    the creator instead of returning silently.

    A shift whose date range has already fully elapsed is skipped entirely by
    load_duty_blocks_from_shifts (nothing left to assign) while still being
    unfilled/not "full" from get_shift_fill's point of view — so it passes the
    "all_shifts_full" creation guard but still yields zero duty blocks once
    the job actually runs.
    """
    node = create_node(admin_session, level="branch", name="n_alg_notif_002")
    dm = create_soldier(admin_session, personal_number="alg_notif_002", role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name="t_alg_notif_002", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="l_alg_notif_002")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 2),
        required_count=1,
    )
    admin_session.add(shift)
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
    assert create_resp.status_code == 202, create_resp.text
    job_id = create_resp.json()["id"]

    poll = None
    for _ in range(20):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] in ("done", "failed"):
            break
        time.sleep(1)

    assert poll is not None
    body = poll.json()
    assert body["status"] == "done", f"expected done, got: {body}"

    admin_session.expire_all()
    notif = admin_session.query(Notification).filter(
        Notification.soldier_id == dm.id,
        Notification.reference_type == "algorithm_job",
        Notification.reference_id == uuid.UUID(job_id),
    ).one_or_none()
    assert notif is not None
    assert notif.type == NotificationType.algorithm_job_done


def test_infeasible_job_notifies_creator(client, admin_session):
    """When the solver cannot find any feasible assignment (zero eligible
    soldiers for the only duty), the job fails with INFEASIBLE and must
    notify the creator."""
    dm, shift = _setup(admin_session, "alg_notif_003")
    soldier = create_soldier(admin_session, personal_number="alg_notif_003s")

    # Fully (globally) exempt BOTH candidate soldiers from every duty type so
    # the solver has zero eligible soldiers for the single required duty —
    # matching the pattern used by test_solve_no_eligible_soldiers.
    et = ExemptionType(name="alg_notif_003_exempt", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add_all([
        SoldierExemption(soldier_id=dm.id, exemption_type_id=et.id, start_date=date(2020, 1, 1)),
        SoldierExemption(soldier_id=soldier.id, exemption_type_id=et.id, start_date=date(2020, 1, 1)),
    ])
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
    assert create_resp.status_code == 202, create_resp.text
    job_id = create_resp.json()["id"]

    poll = None
    for _ in range(20):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] in ("done", "failed"):
            break
        time.sleep(1)

    assert poll is not None
    body = poll.json()
    assert body["status"] == "failed", f"expected failed (INFEASIBLE), got: {body}"

    admin_session.expire_all()
    notif = admin_session.query(Notification).filter(
        Notification.soldier_id == dm.id,
        Notification.reference_type == "algorithm_job",
        Notification.reference_id == uuid.UUID(job_id),
    ).one_or_none()
    assert notif is not None
    assert notif.type == NotificationType.algorithm_job_failed


def test_no_soldiers_or_duties_notifies_creator(admin_session):
    """When there are no active soldiers at all to consider, the job fails
    with error_message="no_soldiers_or_duties" and must notify the creator.

    The real API can't reach this state directly: the job creator is always
    an active soldier themselves (auth requires left_at IS NULL), so the
    global soldier list is never empty for a job they created through the
    endpoint. Instead, build the job row directly and call run_algorithm_job
    the same way the route's background task does, after marking the
    creator's own soldier row as departed (left_at set) so they're excluded
    from load_soldier_inputs while still satisfying the created_by FK.
    """
    node = create_node(admin_session, level="branch", name="n_alg_notif_004")
    dm = create_soldier(admin_session, personal_number="alg_notif_004", role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name="t_alg_notif_004", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="l_alg_notif_004")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2027, 4, 1),
        end_date=date(2027, 4, 2),
        required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()

    # Exclude the creator from load_soldier_inputs (left_at IS NOT NULL) so the
    # active-soldier list is genuinely empty, while created_by FK still resolves.
    dm.left_at = date(2020, 1, 1)

    job = AlgorithmJob(
        planning_start=shift.start_date,
        planning_end=shift.end_date,
        shift_ids=[str(shift.id)],
        settings_json={},
        mode="shadow",
        created_by=dm.id,
    )
    admin_session.add(job)
    admin_session.commit()
    admin_session.refresh(job)

    run_algorithm_job(job.id, dm.id)

    admin_session.expire_all()
    admin_session.refresh(job)
    assert job.status == "failed"
    assert job.error_message == "no_soldiers_or_duties"

    notif = admin_session.query(Notification).filter(
        Notification.soldier_id == dm.id,
        Notification.reference_type == "algorithm_job",
        Notification.reference_id == job.id,
    ).one_or_none()
    assert notif is not None
    assert notif.type == NotificationType.algorithm_job_failed
