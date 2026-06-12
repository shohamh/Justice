import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
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


def test_settings_and_existing_have_reserve_caps() -> None:
    # R defaults to the same value as T and is independent of it.
    s = SolverSettings()
    assert s.T == 8
    assert s.R == 8
    s2 = SolverSettings(T=7, R=11)
    assert s2.R == 11
    # ExistingAssignment carries an is_reserve flag, default False.
    ea = ExistingAssignment(
        soldier_id=uuid4(), duty_type_id=uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
    )
    assert ea.is_reserve is False
    ea_r = ExistingAssignment(
        soldier_id=uuid4(), duty_type_id=uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
        is_reserve=True,
    )
    assert ea_r.is_reserve is True


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


@settings(deadline=None)
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


# Effort helper: the solver optimises quarterly EFFORT
# (post_effort = effort_offset + effort_per_milli × new-duty-score-milli).
# A single-day duty with score_per_day=4 contributes block_milli = 4*1*1000 = 4000.

def _eff_soldier(
    sid: UUID, *, offset: int, per_milli: int, exempt_type: UUID | None = None,
) -> SoldierInput:
    return SoldierInput(
        id=sid, enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("0"), active_days=100,  # unused by the effort objective
        effort_offset=offset, effort_per_milli=per_milli,
        exempted_duty_type_ids={exempt_type} if exempt_type else set(),
    )


def test_does_not_concentrate_duties_on_lowest_effort_soldier() -> None:
    """Regression for the ספקטרה-4-vs-טוקסיק-2 imbalance.

    Two soldiers A and B sit equal mid-pack in effort; F is the lower eligible
    floor; a high-effort soldier (exempt from these duties) sits above. All share
    the same marginal effort_per_milli (equal tenure — the real situation, where
    each duty adds +40_000 effort units here).

    The fair outcome is for F to catch up to A and B and then share evenly:
    F=4, A=1, B=1 → all three converge to the same effort (240_000).

    The OLD objective (min-max + a constant per-soldier history tiebreaker) instead
    dumped ALL six duties onto F (F=6, A=0, B=0): once the pinned max and floor were
    tied, the constant tiebreaker kept preferring the lowest soldier with no
    diminishing return, overshooting fairness. Across runs that drift becomes 5-vs-1.
    """
    A, B, F, high = uuid4(), uuid4(), uuid4(), uuid4()
    duty_type = uuid4()
    loc = uuid4()

    soldiers = [
        _eff_soldier(A, offset=200_000, per_milli=10),
        _eff_soldier(B, offset=200_000, per_milli=10),
        _eff_soldier(F, offset=80_000, per_milli=10),
        _eff_soldier(high, offset=1_000_000, per_milli=10, exempt_type=duty_type),
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d),
                  score_per_day=Decimal("4.00"))
        for d in range(1, 7)
    ]

    result = solve(soldiers, duties, [], SolverSettings(seed=42, time_limit_seconds=15))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 6

    counts = {A: 0, B: 0, F: 0, high: 0}
    for a in result.assignments:
        counts[a.soldier_id] += 1

    assert counts[high] == 0, "exempt high-effort soldier must get nothing"
    assert counts[F] == 4, f"F should catch up to the pack, got {counts}"
    assert counts[A] == 1 and counts[B] == 1, f"equal soldiers must stay balanced, got {counts}"


def test_equal_effort_soldiers_split_evenly() -> None:
    """Two soldiers identical in effort must split new duties evenly, not have one
    arbitrarily soak up the batch."""
    A, B = uuid4(), uuid4()
    duty_type = uuid4()
    loc = uuid4()
    soldiers = [
        _eff_soldier(A, offset=100_000, per_milli=10),
        _eff_soldier(B, offset=100_000, per_milli=10),
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d),
                  score_per_day=Decimal("4.00"))
        for d in range(1, 7)
    ]
    result = solve(soldiers, duties, [], SolverSettings(seed=42, time_limit_seconds=10))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    counts = {A: 0, B: 0}
    for a in result.assignments:
        counts[a.soldier_id] += 1
    assert counts[A] == 3 and counts[B] == 3, f"expected even 3-3 split, got {counts}"


def test_low_marginal_effort_soldier_absorbs_more() -> None:
    """A soldier whose effort barely moves per duty (large W_i → small
    effort_per_milli) legitimately absorbs MORE new duties than one whose effort
    spikes fast, because that is what equalises their post-run effort share. This
    is fair-by-design and must NOT be forced to an equal count.

    The per_milli values must be above the count-space resolution floor (a
    score-4 duty → weight = per_milli×4000 // (EFFORT_SCALE//10000); per_milli=100
    → weight 4, per_milli=1000 → weight 40) so the two marginals are
    distinguishable; below the floor they'd correctly tie."""
    steady = uuid4()   # low marginal effort (count-space weight 4 per duty)
    spiky = uuid4()    # high marginal effort (count-space weight 40 per duty)
    duty_type = uuid4()
    loc = uuid4()
    soldiers = [
        _eff_soldier(steady, offset=0, per_milli=100),
        _eff_soldier(spiky, offset=0, per_milli=1000),
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d),
                  score_per_day=Decimal("4.00"))
        for d in range(1, 7)
    ]
    result = solve(soldiers, duties, [], SolverSettings(seed=42, time_limit_seconds=15))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    counts = {steady: 0, spiky: 0}
    for a in result.assignments:
        counts[a.soldier_id] += 1
    assert counts[steady] > counts[spiky], (
        f"low-marginal-effort soldier should absorb more to equalise effort, got {counts}"
    )


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


def test_count_balance_outranks_reserve_proximity() -> None:
    """Reserve proximity is only a tiebreaker — it must NOT override load balance.

    Two equal-effort soldiers; A is hierarchically close to the reserves (dist 0),
    B is far (dist 10). Two reserve duties fall on different days, so both could go
    to A. Pure proximity would pile both onto A (A=2, B=0); but balancing the load
    must win, splitting them 1-1. (Regression for the fresh-DB 0-vs-13 imbalance,
    where reserve proximity dominated the count tiebreaker ~1000×.)
    """
    s_close = uuid4()
    s_far = uuid4()
    dt = uuid4()
    loc = uuid4()
    soldiers = [
        SoldierInput(id=s_close, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=uuid4()),
        SoldierInput(id=s_far, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=None),
    ]
    reserve_blocks = [
        DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d),
                  score_per_day=Decimal("0.2"), is_reserve=True)
        for d in (1, 2)
    ]
    # s_close is distance 0 from both reserves, s_far is distance 10.
    reserve_dist = {(0, 0): 0, (0, 1): 10, (1, 0): 0, (1, 1): 10}

    result = solve(soldiers, reserve_blocks, [], SolverSettings(seed=1, time_limit_seconds=10),
                   reserve_dist=reserve_dist)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    counts = {s_close: 0, s_far: 0}
    for a in result.assignments:
        counts[a.soldier_id] += 1
    assert counts[s_close] == 1 and counts[s_far] == 1, (
        f"load balance must beat reserve proximity, got {counts}"
    )


# ── Decomposition + batching ──────────────────────────────────────────────────


def test_connected_components_splits_disjoint_eligibility_groups() -> None:
    """Soldiers/duties that share no eligibility form separate components."""
    from app.algorithm.solver import _connected_components, _eligible_pairs

    type_a, type_b = uuid4(), uuid4()
    loc = uuid4()
    # group A: eligible for type_a only (exempt from type_b); group B: vice versa.
    a1 = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                      active_days=100, exempted_duty_type_ids={type_b})
    a2 = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                      active_days=100, exempted_duty_type_ids={type_b})
    b1 = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                      active_days=100, exempted_duty_type_ids={type_a})
    soldiers = [a1, a2, b1]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=type_a, duty_location_id=loc,
                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 1), score_per_day=Decimal("1")),
        DutyBlock(id=uuid4(), duty_type_id=type_b, duty_location_id=loc,
                  start_date=date(2026, 6, 2), end_date=date(2026, 6, 2), score_per_day=Decimal("1")),
    ]
    comps = _connected_components(len(duties), len(soldiers), _eligible_pairs(soldiers, duties))
    # Two components: {duty_a + a1,a2} and {duty_b + b1}.
    assert len(comps) == 2
    sizes = sorted((len(d), len(s)) for d, s in comps)
    assert sizes == [(1, 1), (1, 2)]


def test_batched_solve_covers_all_and_balances_by_effort() -> None:
    """A run larger than batch_size is decomposed/batched, still covers every duty,
    and routes new duties toward LOW-effort soldiers (high-effort get fewer)."""
    duty_type = uuid4()
    loc = uuid4()
    # 6 soldiers, equal marginal; effort_offset descending so soldier 0 is most loaded.
    soldiers = [
        SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, effort_offset=(5 - i) * 2_000_000, effort_per_milli=10_000)
        for i in range(6)
    ]
    # 24 single-day duties over distinct days (> batch_size below).
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                  start_date=date(2026, 6, 1) + timedelta(days=d), end_date=date(2026, 6, 1) + timedelta(days=d),
                  score_per_day=Decimal("1.00"))
        for d in range(24)
    ]
    settings = SolverSettings(batching_enabled=True, batch_size=8, batch_time_limit_seconds=10, T=14, W=14)
    result = solve(soldiers, duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 24  # full coverage across batches

    counts = {s.id: 0 for s in soldiers}
    for a in result.assignments:
        counts[a.soldier_id] += 1
    # soldier 0 (highest effort_offset) should get no more than soldier 5 (lowest).
    assert counts[soldiers[0].id] <= counts[soldiers[5].id], (
        f"high-effort soldier should not get more than low-effort, got {[counts[s.id] for s in soldiers]}"
    )


# ── T/R split-cap tests ───────────────────────────────────────────────────────


def _single_day_duty(dt: date, duty_type: uuid.UUID, *, is_reserve: bool) -> DutyBlock:
    return DutyBlock(
        id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
        start_date=dt, end_date=dt, score_per_day=Decimal("1.00"),
        is_reserve=is_reserve,
    )


def test_window_caps_split_reserve_and_real() -> None:
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    real = [_single_day_duty(base + timedelta(days=i), duty_type, is_reserve=False)
            for i in range(3)]
    reserve = [_single_day_duty(base + timedelta(days=3 + i), duty_type, is_reserve=True)
               for i in range(3)]
    duties = real + reserve  # 6 duties, all within a 14-day window

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5

    # T=2, R=5: must cover all 6, but 6 > R=5 → INFEASIBLE.
    model, _ = build_model(soldiers=soldiers, duties=duties, existing=[],
                           settings=SolverSettings(T=2, R=5, W=14))
    assert solver.Solve(model) == cp_model.INFEASIBLE

    # T=2, R=6: total fits under R, but only 2 of the 3 real duties may be taken...
    # coverage still forces all 3 real → infeasible on T=2.
    model2, _ = build_model(soldiers=soldiers, duties=duties, existing=[],
                            settings=SolverSettings(T=2, R=6, W=14))
    assert solver.Solve(model2) == cp_model.INFEASIBLE

    # T=3, R=6: 3 real (== T) + 3 reserve (total 6 == R) → feasible.
    model3, x3 = build_model(soldiers=soldiers, duties=duties, existing=[],
                             settings=SolverSettings(T=3, R=6, W=14))
    assert solver.Solve(model3) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assigned_real = sum(
        solver.Value(x3[(di, 0)])
        for di, d in enumerate(duties) if not d.is_reserve
    )
    assert assigned_real == 3


def test_relaxation_relaxes_R_before_T() -> None:
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=base + timedelta(days=i), end_date=base + timedelta(days=i),
                  score_per_day=Decimal("1.00"), is_reserve=False)
        for i in range(8)  # 8 real duty-days in a 14-day window
    ]
    result = solve(soldiers, duties, [],
                   SolverSettings(T=7, R=7, W=14, time_limit_seconds=5))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    r_idx = next((i for i, r in enumerate(result.relaxed) if r.startswith("R")), None)
    t_idx = next((i for i, r in enumerate(result.relaxed) if r.startswith("T")), None)
    assert r_idx is not None, f"expected R relaxation, got {result.relaxed}"
    assert t_idx is not None, f"expected T relaxation, got {result.relaxed}"
    assert r_idx < t_idx, f"R must relax before T, got {result.relaxed}"
    assert "R→9" in result.relaxed
    assert "T→9" in result.relaxed


def test_existing_reserve_counts_toward_R_not_T() -> None:
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    # Two existing PUBLISHED RESERVE duty-days in the window.
    existing = [
        ExistingAssignment(soldier_id=soldier_id, duty_type_id=duty_type,
                           start_date=base, end_date=base, is_reserve=True),
        ExistingAssignment(soldier_id=soldier_id, duty_type_id=duty_type,
                           start_date=base + timedelta(days=1),
                           end_date=base + timedelta(days=1), is_reserve=True),
    ]
    # One NEW REAL duty in the same window.
    duties = [_single_day_duty(base + timedelta(days=2), duty_type, is_reserve=False)]

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5

    # T=1 satisfied (1 real ≤ 1, existing reserves don't count toward T),
    # but R=2 violated (2 reserve + 1 real = 3 > 2) → INFEASIBLE.
    model, _ = build_model(soldiers=soldiers, duties=duties, existing=existing,
                           settings=SolverSettings(T=1, R=2, W=14))
    assert solver.Solve(model) == cp_model.INFEASIBLE

    # R=3 gives headroom for the total → FEASIBLE, real duty assigned.
    model2, x2 = build_model(soldiers=soldiers, duties=duties, existing=existing,
                             settings=SolverSettings(T=1, R=3, W=14))
    assert solver.Solve(model2) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(x2[(0, 0)]) == 1


def test_relax_r_ceiling_is_configurable() -> None:
    """A low relax_r_ceiling caps how far R is relaxed, leaving the problem INFEASIBLE."""
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    # 10 real duties in one window — needs T/R ≥ 10 to be feasible.
    duties = [_single_day_duty(base + timedelta(days=i), duty_type, is_reserve=False)
              for i in range(10)]

    # With default ceilings (R=11, T=9) the chain relaxes and finds a solution
    # (T relaxes to 9 which covers all 10 duties... wait, T=9 < 10 so still INFEASIBLE).
    # So: use 5 duties (needs T≥5). Default T_MAX=9 covers it.
    duties5 = duties[:5]
    result_default = solve(soldiers, duties5, [], SolverSettings(T=3, R=3, W=14))
    assert result_default.status in ("OPTIMAL", "FEASIBLE")
    assert "T→5" in result_default.relaxed  # relaxed T from 3 to 5

    # With relax_t_ceiling=3 the chain cannot relax beyond T=3 → INFEASIBLE.
    result_capped = solve(soldiers, duties5, [], SolverSettings(T=3, R=3, W=14,
                                                                relax_r_ceiling=3,
                                                                relax_t_ceiling=3))
    assert result_capped.status == "INFEASIBLE"
    # No relaxation steps taken (already at ceiling).
    assert result_capped.relaxed == []


def test_batched_reserve_carryforward_counts_toward_R_not_T() -> None:
    """A reserve duty assigned in batch N must not consume T headroom in batch N+1.

    Setup: 1 soldier, batch_size=1, T=1, R=3, W=14.
      Batch 0: reserve duty on day 0  → assigned to the only soldier.
      Batch 1: real duty on day 1     → assigned to the only soldier.
    With correct carry-forward (is_reserve=True on the carried ExistingAssignment):
      window [day0, day0+13] has 1 reserve + 1 real → real count = 1 ≤ T=1, total = 2 ≤ R=3 → FEASIBLE.
    With broken carry-forward (is_reserve defaults to False):
      the reserve is treated as real → real count = 2 > T=1 → INFEASIBLE or T relaxation needed.
    """
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    reserve_duty = _single_day_duty(base, duty_type, is_reserve=True)           # day 0
    real_duty = _single_day_duty(base + timedelta(days=1), duty_type, is_reserve=False)  # day 1

    # batch_size=1 forces batching: reserve_duty lands in batch 0, real_duty in batch 1.
    result = solve(
        soldiers=soldiers,
        duties=[reserve_duty, real_duty],
        existing=[],
        settings=SolverSettings(T=1, R=3, W=14, batching_enabled=True, batch_size=1,
                                time_limit_seconds=5),
    )
    assert result.status in ("OPTIMAL", "FEASIBLE"), (
        f"Expected OPTIMAL/FEASIBLE but got {result.status}; relaxed={result.relaxed}"
    )
    # T must never need relaxing: the reserve day should not count toward T.
    t_relaxed = [r for r in result.relaxed if r.startswith("T→")]
    assert not t_relaxed, (
        f"T was relaxed ({t_relaxed}), meaning the reserve was mis-counted as real"
    )
