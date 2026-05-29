import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st
from ortools.sat.python import cp_model

from app.algorithm.model import build_model
from app.algorithm.solver import solve
from app.algorithm.types import (
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
)


def test_build_model_basic() -> None:
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
    assert model.ModelStats()  # type: ignore[attr-defined]  # model has constraints
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assigned = [k for k, v in x.items() if solver.Value(v) == 1]
    assert len(assigned) == 1


def test_solve_basic() -> None:
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


def test_solve_determinism() -> None:
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


def test_solve_no_eligible_soldiers() -> None:
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


def test_infeasibility_relaxation() -> None:
    soldier_a = uuid4()
    soldier_b = uuid4()
    duty_type = uuid4()
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=1),
        SoldierInput(id=soldier_b, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("1"), active_days=1),
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                  score_per_day=Decimal("1.00"))
        for _ in range(2)
    ]
    result = solve(soldiers, duties, [], SolverSettings(K=Decimal("0"), time_limit_seconds=5))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.relaxed) > 0  # relaxation was needed


# ── Golden fixture tests ──────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("fixture_name", ["small_balanced.json", "density_stress.json"])
def test_golden_fixture(fixture_name: str) -> None:
    path = FIXTURES / fixture_name
    data = json.loads(path.read_text())
    soldiers = [_dict_to_soldier(sd) for sd in data["soldiers"]]
    duties = [_dict_to_duty(dd) for dd in data["duties"]]
    existing = [_dict_to_existing(ed) for ed in data.get("existing", [])]
    settings_dict = data["settings"]
    settings = SolverSettings(
        K=__import__("decimal").Decimal(settings_dict["K"]),
        T=settings_dict["T"],
        W=settings_dict["W"],
        alpha=__import__("decimal").Decimal(settings_dict.get("alpha", "1.0")),
        beta=__import__("decimal").Decimal(settings_dict.get("beta", "2.0")),
        time_limit_seconds=settings_dict.get("time_limit_seconds", 30),
    )

    result = solve(soldiers, duties, existing, settings)
    assert result.status in ("OPTIMAL", "FEASIBLE"), f"{fixture_name}: {result.status}"
    assert len(result.assignments) == len(duties), f"{fixture_name}: {len(result.assignments)} != {len(duties)}"

    assigned_duty_ids = {a.duty_id for a in result.assignments}
    all_duty_ids = {d.id for d in duties}
    assert assigned_duty_ids == all_duty_ids, "Not all duties assigned"

    soldier_dates: dict[UUID, set[date]] = {}
    duty_map = {d.id: d for d in duties}
    for a in result.assignments:
        d = duty_map[a.duty_id]
        dates = set()
        dt = d.start_date
        while dt <= d.end_date:
            if dt in soldier_dates.get(a.soldier_id, set()):
                pytest.fail(f"Overlap: soldier {a.soldier_id} assigned two duties on {dt}")
            dates.add(dt)
            dt += __import__("datetime").timedelta(days=1)
        soldier_dates.setdefault(a.soldier_id, set()).update(dates)


def _dict_to_soldier(d: dict[str, Any]) -> SoldierInput:
    return SoldierInput(
        id=UUID(d["id"]),
        enrolled_at=date.fromisoformat(d["enrolled_at"]),
        cumulative_score=__import__("decimal").Decimal(d["cumulative_score"]),
        active_days=d["active_days"],
        hierarchy_node_id=UUID(d["hierarchy_node_id"]) if d.get("hierarchy_node_id") else None,
        approved_constraint_dates=[(date.fromisoformat(c[0]), date.fromisoformat(c[1]))
                                    for c in d.get("approved_constraint_dates", [])],
        exempted_duty_type_ids={UUID(x) for x in d.get("exempted_duty_type_ids", [])},
    )


def _dict_to_duty(d: dict[str, Any]) -> DutyBlock:
    return DutyBlock(
        id=UUID(d["id"]),
        duty_type_id=UUID(d["duty_type_id"]),
        duty_location_id=UUID(d["duty_location_id"]),
        start_date=date.fromisoformat(d["start_date"]),
        end_date=date.fromisoformat(d["end_date"]),
        score_per_day=__import__("decimal").Decimal(d["score_per_day"]),
    )


def _dict_to_existing(d: dict[str, Any]) -> ExistingAssignment:
    return ExistingAssignment(
        soldier_id=UUID(d["soldier_id"]),
        duty_type_id=UUID(d["duty_type_id"]),
        start_date=date.fromisoformat(d["start_date"]),
        end_date=date.fromisoformat(d["end_date"]),
    )


# ── Property-based tests ──────────────────────────────────────────────


@given(
    st.lists(
        st.builds(
            SoldierInput,
            id=st.uuids(),
            enrolled_at=st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 12, 31)),
            cumulative_score=st.decimals(min_value=0, max_value=100),
            active_days=st.integers(min_value=10, max_value=500),
            exempted_duty_type_ids=st.sets(st.uuids(), max_size=2),
        ),
        min_size=2,
        max_size=4,
    ),
    st.lists(
        st.builds(
            DutyBlock,
            id=st.uuids(),
            duty_type_id=st.uuids(),
            duty_location_id=st.uuids(),
            start_date=st.dates(min_value=date(2026, 6, 1), max_value=date(2026, 6, 30)),
            end_date=st.dates(min_value=date(2026, 6, 1), max_value=date(2026, 6, 30)),
            score_per_day=st.decimals(min_value=1, max_value=5),
        ).filter(lambda d: d.end_date >= d.start_date),
        min_size=1,
        max_size=3,
    ),
)
def test_hypothesis_property(hyp_soldiers: list[SoldierInput], hyp_duties: list[DutyBlock]) -> None:
    if not _any_eligible(hyp_soldiers, hyp_duties):
        return
    settings = SolverSettings(time_limit_seconds=10)
    result = solve(hyp_soldiers, hyp_duties, [], settings)
    if result.status in ("OPTIMAL", "FEASIBLE"):
        assert len(result.assignments) == len(hyp_duties)
        duty_map = {d.id: d for d in hyp_duties}
        soldier_map = {s.id: s for s in hyp_soldiers}
        for a in result.assignments:
            d = duty_map[a.duty_id]
            s = soldier_map[a.soldier_id]
            assert d.duty_type_id not in s.exempted_duty_type_ids


def _any_eligible(soldiers: list[SoldierInput], duties: list[DutyBlock]) -> bool:
    for d in duties:
        for s in soldiers:
            if d.duty_type_id not in s.exempted_duty_type_ids:
                return True
    return False
