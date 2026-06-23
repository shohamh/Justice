from __future__ import annotations

import pytest
from datetime import date
from decimal import Decimal

from app.db.models import AlgorithmJob, DutyAssignment, DutyLocation, DutyType
from tests.helpers import create_node, create_soldier


def _setup_job(session, pn_suffix: str):
    dt = DutyType(name=f"שמירה_{pn_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"שער_{pn_suffix}")
    session.add(dt)
    session.add(loc)
    session.flush()
    node = create_node(session, level="branch", name=f"node_{pn_suffix}")
    dm = create_soldier(
        session,
        personal_number=f"perf_dm_{pn_suffix}",
        role="duty_manager",
        hierarchy_node_id=node.id,
    )
    job = AlgorithmJob(
        planning_start=date(2027, 2, 1),
        planning_end=date(2027, 2, 7),
        shift_ids=[],
        settings_json={},
        mode="shadow",
        created_by=dm.id,
        status="done",
    )
    session.add(job)
    session.flush()
    return dt, loc, dm, job


def test_proposals_fast_path_returns_proposals(admin_session):
    from app.routes.algorithm import _proposals_for_job

    dt, loc, dm, job = _setup_job(admin_session, "fp1")
    soldier = create_soldier(admin_session, personal_number="perf_s_fp1")

    assignment = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 2),
        status="algorithm_draft",
        algorithm_job_id=job.id,
        norm_score_before=0.4,
        norm_score_after=0.6,
        candidate_rank=1,
        candidate_pool_size=5,
    )
    admin_session.add(assignment)
    admin_session.commit()

    proposals = _proposals_for_job(admin_session, job)

    assert len(proposals) == 1
    p = proposals[0]
    assert p.assignment_id == assignment.id
    assert p.soldier_id == soldier.id
    assert p.norm_score_before == pytest.approx(0.4)
    assert p.norm_score_after == pytest.approx(0.6)
    assert p.candidate_rank == 1
    assert p.candidate_pool_size == 5
    assert p.reserve_assignment_id is None


def test_proposals_fast_path_no_audit_log_dependency(admin_session):
    """Fast path must return proposals without any audit_log rows present."""
    from app.routes.algorithm import _proposals_for_job

    dt, loc, dm, job = _setup_job(admin_session, "fp2")
    soldier = create_soldier(admin_session, personal_number="perf_s_fp2")

    assignment = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 2),
        status="algorithm_draft",
        algorithm_job_id=job.id,
        norm_score_before=0.1,
        norm_score_after=0.2,
        candidate_rank=3,
        candidate_pool_size=8,
    )
    admin_session.add(assignment)
    admin_session.commit()

    proposals = _proposals_for_job(admin_session, job)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.norm_score_before == pytest.approx(0.1)
    assert p.norm_score_after == pytest.approx(0.2)
    assert p.candidate_rank == 3
    assert p.candidate_pool_size == 8


def test_proposals_pending_job_returns_empty(admin_session):
    from app.routes.algorithm import _proposals_for_job

    _, _, dm, job = _setup_job(admin_session, "fp3")
    job.status = "pending"
    admin_session.commit()

    proposals = _proposals_for_job(admin_session, job)
    assert proposals == []
