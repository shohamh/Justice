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
    EFFORT_SCALE,
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
    duty_type = uuid4()
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100),
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                  score_per_day=Decimal("1.00")),
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=date(2026, 6, 2), end_date=date(2026, 6, 2),
                  score_per_day=Decimal("1.00")),
    ]
    # Force infeasibility: 1 soldier must cover both duties (coverage constraint),
    # but T=1, W=2 allows at most 1 duty-day in any 2-day window.
    # The window [June 1, June 2] contains both → violates T=1.
    # The relaxation chain should raise T→2 and find a feasible solution.
    result = solve(soldiers, duties, [], SolverSettings(T=1, W=2, time_limit_seconds=5))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.relaxed) > 0  # T was relaxed


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
        T=settings_dict["T"],
        W=settings_dict["W"],
        alpha=__import__("decimal").Decimal(settings_dict.get("alpha", "1.0")),
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


def test_reserve_blocks_prefer_closer_soldier() -> None:
    """With two soldiers in different hierarchy nodes, the reserve block should
    be assigned to the soldier closer to the primary candidate nodes.

    Hierarchy: node_a -> root (3 nodes in ancestors: node_a, root + itself)
               node_b -> node_b only (no parent registered, so ancestors = {node_b})
    Only s_close has a known hierarchy node for primary-node computation,
    so s_far (no soldier_node entry) gets distance=10 (unknown), s_close dist=0.
    The high gamma (5.0) ensures s_close wins the reserve assignment.
    """
    root = uuid4(); node_a = uuid4()
    dt = uuid4(); loc = uuid4()
    s_close = uuid4(); s_far = uuid4()

    soldiers = [
        SoldierInput(id=s_close, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=node_a),
        SoldierInput(id=s_far, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=None),
    ]
    shift_id = uuid4()
    primary_block = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                               start_date=date(2026,6,1), end_date=date(2026,6,1),
                               score_per_day=Decimal("1"), is_reserve=False)
    reserve_block = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                               start_date=date(2026,6,2), end_date=date(2026,6,2),
                               score_per_day=Decimal("0.2"), is_reserve=True)
    block_to_shift = {primary_block.id: shift_id, reserve_block.id: shift_id}

    hierarchy_parent: dict[UUID, UUID | None] = {node_a: root, root: None}
    # Only s_close has a known node; s_far will get distance=10 (unknown)
    soldier_node: dict[UUID, UUID] = {s_close: node_a}

    from app.algorithm.reserve import compute_reserve_dist
    reserve_dist = compute_reserve_dist(
        soldiers=soldiers,
        duties=[primary_block, reserve_block],
        block_to_shift=block_to_shift,
        hierarchy_parent=hierarchy_parent,
        soldier_node=soldier_node,
    )
    # s_close -> dist 0 (node_a is a primary node), s_far -> dist 10 (no node)
    assert reserve_dist[(1, 0)] == 0   # reserve_block(idx=1), s_close(idx=0)
    assert reserve_dist[(1, 1)] == 10  # reserve_block(idx=1), s_far(idx=1)

    settings = SolverSettings(time_limit_seconds=10, reserve_hierarchy_weight=Decimal("5.0"))
    result = solve(soldiers=soldiers, duties=[primary_block, reserve_block],
                   existing=[], settings=settings, reserve_dist=reserve_dist)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    reserve_assignment = next(a for a in result.assignments if a.duty_id == reserve_block.id)
    assert reserve_assignment.soldier_id == s_close


def test_effort_objective_l1_prefers_lower_effort_over_lower_score_per_day() -> None:
    """The L1 effort objective should assign the duty to the soldier with lower
    historical effort score (low_effort), even though the old score_per_day
    objective would have preferred high_effort (whose score_per_day is 0).

    Setup:
      - 1 duty: 1 day, score_per_day=1.0  →  _block_score = 1 000 milli
      - unit_score_milli = 1 000, C_over_D = 1.0
        → effort_per_milli = EFFORT_SCALE // 1 000 = 1 000 000

      high_effort: cumulative_score=0, active_days=1000 (spd=0.000)
                   effort_offset = 50% × EFFORT_SCALE (high historical load)
      low_effort:  cumulative_score=5, active_days=50  (spd=0.100)
                   effort_offset = 10% × EFFORT_SCALE (low historical load)

    Old score_per_day objective:
      assigning to high_effort → max_norm = (0+1000)/1000 = 1   ← preferred
      assigning to low_effort  → max_norm = (5000+1000)/50 = 120

    New L1 effort objective:
      assigning to high_effort → efforts {1 500M, 100M} → total dev = 1 400M
      assigning to low_effort  → efforts {500M, 1 100M} → total dev =   600M ← preferred
    """
    dt = uuid4()
    loc = uuid4()
    effort_per_milli = EFFORT_SCALE // 1000  # = 1_000_000

    high_effort = uuid4()
    low_effort = uuid4()

    soldiers = [
        SoldierInput(
            id=high_effort,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=1000,
            effort_offset=int(0.5 * EFFORT_SCALE),
            effort_per_milli=effort_per_milli,
        ),
        SoldierInput(
            id=low_effort,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("5"),
            active_days=50,
            effort_offset=int(0.1 * EFFORT_SCALE),
            effort_per_milli=effort_per_milli,
        ),
    ]
    duties = [
        DutyBlock(
            id=uuid4(),
            duty_type_id=dt,
            duty_location_id=loc,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            score_per_day=Decimal("1.00"),
        )
    ]

    result = solve(
        soldiers=soldiers,
        duties=duties,
        existing=[],
        settings=SolverSettings(time_limit_seconds=10),
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].soldier_id == low_effort
