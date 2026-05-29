from datetime import date
from decimal import Decimal
from uuid import uuid4

from ortools.sat.python import cp_model

from app.algorithm.model import build_model
from app.algorithm.solver import solve
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverResult,
    SolverSettings,
)


def test_build_model_basic():
    soldier_id = uuid4()
    duty_id = uuid4()
    soldiers = [
        SoldierInput(
            id=soldier_id,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=100,
        )
    ]
    duties = [
        DutyBlock(
            id=duty_id,
            duty_type_id=uuid4(),
            duty_location_id=uuid4(),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            score_per_day=Decimal("1.00"),
        )
    ]
    existing: list[ExistingAssignment] = []
    settings = SolverSettings()
    model, x = build_model(soldiers=soldiers, duties=duties, existing=existing, settings=settings)
    assert len(x) == 1  # one eligible (duty, soldier) pair
    assert model.ModelStats()  # model has constraints
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assigned = [k for k, v in x.items() if solver.Value(v) == 1]
    assert len(assigned) == 1


def test_solve_basic():
    soldier_id = uuid4()
    duty_id = uuid4()
    soldiers = [
        SoldierInput(
            id=soldier_id,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=100,
        )
    ]
    duties = [
        DutyBlock(
            id=duty_id,
            duty_type_id=uuid4(),
            duty_location_id=uuid4(),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            score_per_day=Decimal("1.00"),
        )
    ]
    existing: list[ExistingAssignment] = []
    settings = SolverSettings(time_limit_seconds=10)
    result = solve(soldiers=soldiers, duties=duties, existing=existing, settings=settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].soldier_id == soldier_id


def test_solve_determinism():
    soldier_id = uuid4()
    duties = [DutyBlock(id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    settings = SolverSettings(seed=42, time_limit_seconds=10)
    r1 = solve(soldiers, duties, [], settings)
    r2 = solve(soldiers, duties, [], settings)
    assert r1.assignments == r2.assignments
    assert r1.objective_value == r2.objective_value


def test_solve_no_eligible_soldiers():
    soldier_id = uuid4()
    exempt_type = uuid4()
    duty_type = exempt_type
    duties = [DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                        score_per_day=Decimal("1.00"))]
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100,
                             exempted_duty_type_ids={exempt_type})]
    result = solve(soldiers, duties, [], SolverSettings(time_limit_seconds=5))
    assert result.status == "INFEASIBLE"
    assert len(result.assignments) == 0


def test_infeasibility_relaxation():
    soldier_a = uuid4()
    soldier_b = uuid4()
    duty_type = uuid4()
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=soldier_b, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("10"), active_days=100),
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                  score_per_day=Decimal("1.00"))
        for _ in range(2)
    ]
    result = solve(soldiers, duties, [], SolverSettings(K=Decimal("1"), time_limit_seconds=5))
    assert result.status in ("OPTIMAL", "FEASIBLE")
