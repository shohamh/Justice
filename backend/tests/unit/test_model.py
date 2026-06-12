"""Unit tests for the CP-SAT model: score preference and density constraints."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.algorithm.model import build_model
from app.algorithm.types import EFFORT_SCALE, DutyBlock, ExistingAssignment, SoldierInput, SolverSettings
from ortools.sat.python.cp_model import CpSolver


def _soldier(score: float, active_days: int = 100) -> SoldierInput:
    cum = Decimal(str(score))
    # The model optimises quarterly EFFORT, not cumulative_score. Mirror the
    # historical load as effort (score_per_day × EFFORT_SCALE) with a uniform
    # marginal so these score-based scenarios drive the effort objective.
    return SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2025, 1, 1),
        cumulative_score=cum,
        active_days=active_days,
        effort_offset=int(cum * EFFORT_SCALE / active_days),
        effort_per_milli=EFFORT_SCALE // (active_days * 1000),
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


def test_fairness_all_zero_scores_distributes():
    """The core bug: when all soldiers have zero score the algorithm must still distribute
    duties evenly — not concentrate them on one person arbitrarily."""
    s1, s2, s3 = _soldier(0.0), _soldier(0.0), _soldier(0.0)
    # Three non-overlapping single-day duties
    d1 = _duty(date(2026, 9, 1))
    d2 = _duty(date(2026, 9, 8))
    d3 = _duty(date(2026, 9, 15))

    assigned = _solve([s1, s2, s3], [d1, d2, d3], T=7, W=14, alpha=Decimal("1.0"))

    soldiers_used = set(assigned.values())
    assert len(soldiers_used) == 3, (
        f"All 3 soldiers should each get 1 duty, but only {len(soldiers_used)} were used"
    )


def test_alpha_prefers_lower_score_soldier():
    """With alpha > 0 the solver assigns the single duty to the soldier with score 0, not score 8."""
    low = _soldier(score=0.0)
    high = _soldier(score=8.0)
    duty = _duty(date(2026, 7, 1))

    assigned = _solve([low, high], [duty], T=7, W=14, alpha=Decimal("1.0"))

    assert assigned[duty.id] == low.id, "Expected low-score soldier to be assigned"


def test_alpha_zero_no_score_preference():
    """With alpha=0 the solver has no score preference — feasible with either soldier."""
    low = _soldier(score=0.0)
    high = _soldier(score=8.0)
    duty = _duty(date(2026, 7, 1))

    # Just assert it's feasible; don't care which soldier is chosen
    assigned = _solve([low, high], [duty], T=7, W=14, alpha=Decimal("0"))
    assert duty.id in assigned


def test_density_hard_constraint_infeasible_when_violated():
    """With T=1, W=2 and 1 soldier covering 2 consecutive duties, solver must be INFEASIBLE."""
    solo = _soldier(score=0.0)
    d1 = _duty(date(2026, 8, 1))
    d2 = _duty(date(2026, 8, 2))

    settings = SolverSettings(T=1, W=2, alpha=Decimal("0"))
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

    assigned = _solve([s1, s2], [d1, d2], T=1, W=2, alpha=Decimal("0"))

    assert assigned[d1.id] != assigned[d2.id], "Consecutive duties must go to different soldiers"


def test_high_historical_score_does_not_monopolize_run():
    """Regression: a soldier with a large published (historical) score used to 'pin'
    the max-norm ceiling, making the algorithm indifferent to how it distributes new
    assignments among zero-score soldiers.  The fix uses incremental (this-run) norm
    as the primary objective so the high-history soldier no longer dominates.

    Setup: 1 high-score soldier + 3 zero-score soldiers, 3 non-overlapping duties.
    Expected: each zero-score soldier gets exactly one duty; the high-score soldier
    gets nothing (because every assignment to them raises the incremental max more
    than spreading to zero-score soldiers does)."""
    high = _soldier(score=30.0)
    low1 = _soldier(score=0.0)
    low2 = _soldier(score=0.0)
    low3 = _soldier(score=0.0)

    d1 = _duty(date(2026, 10, 1))
    d2 = _duty(date(2026, 10, 8))
    d3 = _duty(date(2026, 10, 15))

    assigned = _solve(
        [high, low1, low2, low3], [d1, d2, d3],
        T=7, W=14, alpha=Decimal("1.0"),
    )

    assert high.id not in assigned.values(), (
        "High-score soldier should receive no new duties when zero-score soldiers are available"
    )
    soldiers_used = set(assigned.values())
    assert soldiers_used == {low1.id, low2.id, low3.id}, (
        f"Each zero-score soldier should get exactly one duty; got {soldiers_used}"
    )
