from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.explain import build_explanations
from app.algorithm.types import Assignment, CandidateInfo, DutyBlock, ExplanationData, SoldierInput


def test_build_explanations_basic():
    soldier_id = uuid4()
    duty_id = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    duties = [DutyBlock(id=duty_id, duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duty_id, soldier_id=soldier_id)]
    result = build_explanations(
        soldiers=soldiers,
        duties=duties,
        assignments=assignments,
        global_before={"min_gap": 0, "norm_variance": 0},
        global_after={"min_gap": 5, "norm_variance": 1},
        solver_seed=42,
    )
    assert len(result.per_assignment) == 1
    assert result.per_assignment[0].duty_id == duty_id
    assert result.per_assignment[0].assigned_soldier_id == soldier_id
    assert any(
        c.soldier_id == soldier_id and not c.blocked
        for c in result.per_assignment[0].candidates
    )
    assert result.algorithm_version == "cp-sat-1.0"
    assert result.solver_seed == 42


def test_explain_blocked_candidate():
    soldier_a = uuid4()
    soldier_b = uuid4()
    duty_type = uuid4()
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=soldier_b, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     exempted_duty_type_ids={duty_type}),
    ]
    duties = [DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=soldier_a)]
    result = build_explanations(soldiers, duties, assignments, {}, {}, 42)
    entry = result.per_assignment[0]
    blocked = [c for c in entry.candidates if c.blocked]
    unblocked = [c for c in entry.candidates if not c.blocked]
    assert len(blocked) == 1
    assert "exemption" in blocked[0].blocking_constraints
    assert len(unblocked) == 1
    assert unblocked[0].soldier_id == soldier_a
