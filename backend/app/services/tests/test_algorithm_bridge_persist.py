from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.algorithm.types import Assignment, DutyBlock, ExplanationData, SolverResult
from app.db.models import AlgorithmJob, DutyAssignment, DutyLocation, DutyType
from app.services.algorithm_bridge import persist_results
from tests.helpers import create_soldier


def test_persist_results_copies_block_times_onto_assignment(admin_session):
    dt = DutyType(name="dt_persist_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_persist_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()

    soldier = create_soldier(admin_session, personal_number="8400201")

    block = DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        score_per_day=Decimal("1"),
        start_time="08:00",
        end_time="17:00",
    )

    result = SolverResult(
        assignments=[Assignment(duty_id=block.id, soldier_id=soldier.id)],
        status="ok",
    )
    explanation_data = ExplanationData()

    job = AlgorithmJob(
        planning_start=date(2026, 6, 1),
        planning_end=date(2026, 6, 2),
        shift_ids=[],
        settings_json={},
        mode="full",
    )
    admin_session.add(job)
    admin_session.flush()

    persist_results(
        admin_session,
        job=job,
        result=result,
        explanation_data=explanation_data,
        duty_blocks=[block],
        soldier_names={soldier.id: soldier.full_name},
        actor_id=None,
    )

    da = (
        admin_session.query(DutyAssignment)
        .filter(DutyAssignment.status == "algorithm_draft")
        .one()
    )
    assert da.start_time == "08:00"
    assert da.end_time == "17:00"
