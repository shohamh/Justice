"""Unit tests for the CP-SAT model: score preference and density constraints."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.algorithm.model import build_model
from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings
from ortools.sat.python.cp_model import CpSolver


def _soldier(score: float, active_days: int = 100) -> SoldierInput:
    return SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2025, 1, 1),
        cumulative_score=Decimal(str(score)),
        active_days=active_days,
    )


def _duty(start: date, end: date | None = None, score: float = 1.0) -> DutyBlock:
    return DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=uuid.uuid4(),
        duty_location_id=uuid.uuid4(),
        start_date=start,
        end_date=end or start,
        score_per_day=Decimal(str(score)),
    )


def _solve(soldiers, duties, existing=None, **settings_kwargs):
    settings = SolverSettings(**settings_kwargs)
    model, x = build_model(soldiers, duties, existing or [], settings)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 10
    status = solver.Solve(model)
    assert solver.StatusName(status) in ("OPTIMAL", "FEASIBLE"), f"Unexpected status: {solver.StatusName(status)}"
    assigned: dict[uuid.UUID, uuid.UUID] = {}
    for (di, si), var in x.items():
        if solver.Value(var):
            assigned[duties[di].id] = soldiers[si].id
    return assigned


def test_alpha_prefers_lower_score_soldier():
    """With alpha > 0 the solver assigns the single duty to the soldier with score 0, not score 8."""
    low = _soldier(score=0.0)
    high = _soldier(score=8.0)
    duty = _duty(date(2026, 7, 1))

    assigned = _solve([low, high], [duty], K=Decimal("20"), T=7, W=14, alpha=Decimal("1.0"))

    assert assigned[duty.id] == low.id, "Expected low-score soldier to be assigned"


def test_alpha_zero_no_score_preference():
    """With alpha=0 the solver has no score preference — feasible with either soldier."""
    low = _soldier(score=0.0)
    high = _soldier(score=8.0)
    duty = _duty(date(2026, 7, 1))

    # Just assert it's feasible; don't care which soldier is chosen
    assigned = _solve([low, high], [duty], K=Decimal("20"), T=7, W=14, alpha=Decimal("0"))
    assert duty.id in assigned


def test_density_hard_constraint_infeasible_when_violated():
    """With T=1, W=2 and 1 soldier covering 2 consecutive duties, solver must be INFEASIBLE."""
    solo = _soldier(score=0.0)
    d1 = _duty(date(2026, 8, 1))
    d2 = _duty(date(2026, 8, 2))

    settings = SolverSettings(K=Decimal("20"), T=1, W=2, alpha=Decimal("0"))
    model, x = build_model([solo], [d1, d2], [], settings)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)
    assert solver.StatusName(status) == "INFEASIBLE"


def test_density_hard_constraint_distributes_across_soldiers():
    """With T=1, W=2 and 2 soldiers, 2 consecutive duties are assigned to different soldiers."""
    s1 = _soldier(score=0.0)
    s2 = _soldier(score=0.0)
    d1 = _duty(date(2026, 8, 1))
    d2 = _duty(date(2026, 8, 2))

    assigned = _solve([s1, s2], [d1, d2], K=Decimal("20"), T=1, W=2, alpha=Decimal("0"))

    assert assigned[d1.id] != assigned[d2.id], "Consecutive duties must go to different soldiers"
