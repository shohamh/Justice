import json
import threading
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


def test_settings_have_decomposition_fields() -> None:
    s = SolverSettings()
    assert s.decomposition == "effort_rounds"
    assert s.round_soldier_count == 20
    assert SolverSettings(decomposition="calendar").decomposition == "calendar"


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
    # R defaults to 15 (wider window than T=8 to allow reserve headroom).
    s = SolverSettings()
    assert s.T == 8
    assert s.R == 15
    assert s.Wt == 14
    assert s.Wr == 28
    s2 = SolverSettings(T=7, R=11)
    assert s2.R == 11
    # ExistingAssignment carries an is_reserve flag, default False.
    ea = ExistingAssignment(
        soldier_id=uuid4(), duty_type_id=uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    assert ea.is_reserve is False
    ea_r = ExistingAssignment(
        soldier_id=uuid4(), duty_type_id=uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        is_reserve=True,
    )
    assert ea_r.is_reserve is True


def test_solve_no_eligible_soldiers() -> None:
    soldier_id = uuid4()
    exempt_type = uuid4()
    duty_type = exempt_type
    duties = [DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
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
                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                  score_per_day=Decimal("1.00")),
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=date(2026, 6, 2), end_date=date(2026, 6, 3),
                  score_per_day=Decimal("1.00")),
    ]
    # Force infeasibility: 1 soldier must cover both duties (coverage constraint),
    # but T=1, W=2 allows at most 1 duty-day in any 2-day window.
    # The window [June 1, June 2] contains both → violates T=1.
    # The relaxation chain should raise T→2 and find a feasible solution.
    result = solve(soldiers, duties, [], SolverSettings(T=1, Wt=2, Wr=4, time_limit_seconds=5))
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
        Wt=settings_dict.get("Wt", settings_dict.get("W", 14)),
        Wr=settings_dict.get("Wr", settings_dict.get("W", 28)),
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
        while dt < d.end_date:
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
        # Coverage is best-effort: an over-subscribed instance (e.g. two same-day
        # duties with only one eligible soldier) can return FEASIBLE with some duties
        # left unassigned. Assert the validity of what WAS assigned — not completeness.
        assert len(result.assignments) <= len(hyp_duties)
        assigned_duty_ids = [a.duty_id for a in result.assignments]
        assert len(assigned_duty_ids) == len(set(assigned_duty_ids))  # each duty at most once
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
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d) + timedelta(days=1),
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
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d) + timedelta(days=1),
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
                  start_date=date(2026, 6, d), end_date=date(2026, 6, d) + timedelta(days=1),
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
    """A run spanning multiple calendar windows is decomposed/batched, still covers every duty,
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
    settings = SolverSettings(batching_enabled=True, batch_window_days=8, batch_time_limit_seconds=10, T=14, Wt=14, Wr=28)
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
        start_date=dt, end_date=dt + timedelta(days=1), score_per_day=Decimal("1.00"),
        is_reserve=is_reserve,
    )


def test_soft_coverage_covers_max_without_infeasible() -> None:
    s_id = uuid4(); dt = uuid4()
    soldiers = [SoldierInput(id=s_id, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100)]
    day = date(2026, 6, 1)
    duties = [_single_day_duty(day, dt, is_reserve=False), _single_day_duty(day, dt, is_reserve=False)]
    from app.algorithm.solver import _solve_soft_coverage
    hard = build_model(soldiers=soldiers, duties=duties, existing=[], settings=SolverSettings())
    solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = 5
    assert solver.Solve(hard[0]) == cp_model.INFEASIBLE
    res = _solve_soft_coverage(soldiers, duties, [], SolverSettings(time_limit_seconds=5), reserve_dist=None)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert len(res.assignments) == 1


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
                           settings=SolverSettings(T=2, R=5, Wt=14, Wr=28))
    assert solver.Solve(model) == cp_model.INFEASIBLE

    # T=2, R=6: total fits under R, but only 2 of the 3 real duties may be taken...
    # coverage still forces all 3 real → infeasible on T=2.
    model2, _ = build_model(soldiers=soldiers, duties=duties, existing=[],
                            settings=SolverSettings(T=2, R=6, Wt=14, Wr=28))
    assert solver.Solve(model2) == cp_model.INFEASIBLE

    # T=3, R=6: 3 real (== T) + 3 reserve (total 6 == R) → feasible.
    model3, x3 = build_model(soldiers=soldiers, duties=duties, existing=[],
                             settings=SolverSettings(T=3, R=6, Wt=14, Wr=28))
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
                  start_date=base + timedelta(days=i), end_date=base + timedelta(days=i + 1),
                  score_per_day=Decimal("1.00"), is_reserve=False)
        for i in range(8)  # 8 real duty-days in a 14-day window
    ]
    result = solve(soldiers, duties, [],
                   SolverSettings(T=7, R=7, Wt=14, Wr=14, time_limit_seconds=5))
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
                           start_date=base, end_date=base + timedelta(days=1), is_reserve=True),
        ExistingAssignment(soldier_id=soldier_id, duty_type_id=duty_type,
                           start_date=base + timedelta(days=1),
                           end_date=base + timedelta(days=2), is_reserve=True),
    ]
    # One NEW REAL duty in the same window.
    duties = [_single_day_duty(base + timedelta(days=2), duty_type, is_reserve=False)]

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5

    # T=1 satisfied (1 real ≤ 1, existing reserves don't count toward T),
    # but R=2 violated (2 reserve + 1 real = 3 > 2) → INFEASIBLE.
    model, _ = build_model(soldiers=soldiers, duties=duties, existing=existing,
                           settings=SolverSettings(T=1, R=2, Wt=14, Wr=28))
    assert solver.Solve(model) == cp_model.INFEASIBLE

    # R=3 gives headroom for the total → FEASIBLE, real duty assigned.
    model2, x2 = build_model(soldiers=soldiers, duties=duties, existing=existing,
                             settings=SolverSettings(T=1, R=3, Wt=14, Wr=28))
    assert solver.Solve(model2) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(x2[(0, 0)]) == 1


def test_effort_rounds_covers_what_calendar_drops() -> None:
    # Demonstrates that effort-rounds fully covers a continuous/dense schedule
    # within generous default relaxation ceilings, and covers at least as much as
    # the calendar decomposition.
    # Instance: 12 duties over 12 days, 6 soldiers, generous T/R caps.
    # With round_soldier_count=50 all soldiers are in one group (Phase 1 covers all).
    dt = uuid4()
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100)
                for _ in range(6)]
    base = date(2026, 6, 1)
    duties = [_single_day_duty(base + timedelta(days=i), dt, is_reserve=False) for i in range(12)]
    cal = solve(soldiers, duties, [], SolverSettings(decomposition="calendar", batch_window_days=14,
                Wt=14, Wr=28, T=8, R=15,
                batch_time_limit_seconds=10, time_limit_seconds=10))
    er  = solve(soldiers, duties, [], SolverSettings(decomposition="effort_rounds", round_soldier_count=50,
                Wt=14, Wr=28, T=8, R=15,
                batch_time_limit_seconds=10, time_limit_seconds=10))
    assert er.status in ("OPTIMAL", "FEASIBLE")
    assert len(er.assignments) == len(duties), (
        f"effort-rounds should fully cover all {len(duties)} duties, got {len(er.assignments)}"
    )
    assert len(er.assignments) >= len(cal.assignments), (
        f"effort-rounds should cover at least as much as calendar: {len(er.assignments)} < {len(cal.assignments)}"
    )
    assert "LAST_RESORT" not in er.relaxed, f"unexpected LAST_RESORT in er.relaxed: {er.relaxed}"


def test_effort_rounds_respects_ceilings_leaves_partial() -> None:
    # Over-capacity instance: 1 soldier, 2 single-day duties on consecutive days
    # within the same density window (Wt=2, Wr=2), with ceilings == base caps so
    # NO relaxation is allowed (relax_t_ceiling=1, relax_r_ceiling=1).
    # Only 1 of 2 duties can be assigned; the second must be left unassigned.
    dt = uuid4()
    soldier_id = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    duties = [
        _single_day_duty(base, dt, is_reserve=False),              # day 0
        _single_day_duty(base + timedelta(days=1), dt, is_reserve=False),  # day 1
    ]
    # T=1, Wt=2: at most 1 duty-day in any 2-day window; relax ceilings == T=1 so no relaxation allowed.
    result = solve(
        soldiers, duties, [],
        SolverSettings(
            T=1, Wt=2, R=1, Wr=2,
            relax_t_ceiling=1, relax_r_ceiling=1,
            round_soldier_count=50,
            batch_time_limit_seconds=10,
            time_limit_seconds=10,
        ),
    )
    assert result.status in ("OPTIMAL", "FEASIBLE"), (
        f"expected OPTIMAL or FEASIBLE for partial coverage, got {result.status}"
    )
    assert len(result.assignments) == 1, (
        f"only 1 of 2 duties should be assigned within the ceiling, got {len(result.assignments)}"
    )
    assert "LAST_RESORT" not in result.relaxed, (
        f"LAST_RESORT must not appear after removal: {result.relaxed}"
    )
    # The solver must not assign both duties to the same soldier on different days
    # when T=1 in a 2-day window — only one assignment is valid.
    assigned_soldier_ids = {a.soldier_id for a in result.assignments}
    assert assigned_soldier_ids == {soldier_id}


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
    # Use batching_enabled=False to exercise _infeasibility_relaxation_chain directly;
    # the effort-rounds path respects relaxation ceilings absolutely (no last-resort).
    duties5 = duties[:5]
    result_default = solve(soldiers, duties5, [], SolverSettings(T=3, R=3, Wt=14, Wr=14,
                                                                 batching_enabled=False))
    assert result_default.status in ("OPTIMAL", "FEASIBLE")
    assert "T→5" in result_default.relaxed  # relaxed T from 3 to 5

    # With relax_t_ceiling=3 the chain cannot relax beyond T=3 → INFEASIBLE.
    result_capped = solve(soldiers, duties5, [], SolverSettings(T=3, R=3, Wt=14, Wr=14,
                                                                relax_r_ceiling=3,
                                                                relax_t_ceiling=3,
                                                                batching_enabled=False))
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
        settings=SolverSettings(T=1, R=3, Wt=14, Wr=14, batching_enabled=True, batch_window_days=1,
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


def test_settings_have_decomposition_fields() -> None:
    s = SolverSettings()
    assert s.decomposition == "effort_rounds"
    assert s.round_soldier_count == 20
    assert SolverSettings(decomposition="calendar").decomposition == "calendar"


def test_calendar_window_batches_groups_by_start_date():
    """Calendar window batching must group duties whose start_date falls within
    [window_start, window_start + batch_window_days), advancing the window start
    to each new duty's date when that duty would exceed the window."""
    from app.algorithm.solver import _calendar_window_batches
    from app.algorithm.types import DutyBlock
    import uuid
    from datetime import date
    from decimal import Decimal

    def _blk(d: date) -> DutyBlock:
        return DutyBlock(
            id=uuid.uuid4(),
            duty_type_id=uuid.uuid4(),
            duty_location_id=uuid.uuid4(),
            start_date=d,
            end_date=d,
            score_per_day=Decimal("1.0"),
        )

    # 3 duties in first window (Jan 1-28), 2 duties in second window (Feb 1-28)
    duties = [
        _blk(date(2027, 1, 1)),
        _blk(date(2027, 1, 15)),
        _blk(date(2027, 1, 28)),
        _blk(date(2027, 2, 1)),
        _blk(date(2027, 2, 20)),
    ]
    idxs = list(range(5))
    batches = _calendar_window_batches(idxs, duties, batch_window_days=28)
    assert len(batches) == 2
    assert batches[0] == [0, 1, 2]
    assert batches[1] == [3, 4]


def test_decomposed_solve_returns_batch_results() -> None:
    """_decomposed_solve collects BatchResult with correct counts per batch."""
    from app.algorithm.types import BatchResult

    soldier_ids = [uuid4() for _ in range(3)]
    duty_type_id = uuid4()
    duty_location_id = uuid4()
    soldiers = [
        SoldierInput(
            id=sid,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=200,
        )
        for sid in soldier_ids
    ]
    # Two duties far apart → two calendar batches (window=28 days)
    duties = [
        DutyBlock(
            id=uuid4(),
            duty_type_id=duty_type_id,
            duty_location_id=duty_location_id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            score_per_day=Decimal("1.00"),
        ),
        DutyBlock(
            id=uuid4(),
            duty_type_id=duty_type_id,
            duty_location_id=duty_location_id,
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 15),
            score_per_day=Decimal("1.00"),
        ),
    ]
    s = SolverSettings(batch_window_days=28, decomposition="calendar")
    result = solve(soldiers, duties, [], s)

    assert len(result.batch_results) >= 2, "expected at least 2 batches for duties 44 days apart"
    for br in result.batch_results:
        assert isinstance(br, BatchResult)
        assert br.duty_count >= 1
        assert br.soldier_count >= 1
        assert br.outcome in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "CANCELLED")
        assert br.wall_time_seconds >= 0.0
    total_assigned = sum(br.assigned_count for br in result.batch_results)
    assert total_assigned == len(result.assignments)


def _line_duties(base, dt, n, is_reserve=False):
    return [_single_day_duty(base + timedelta(days=i), dt, is_reserve=is_reserve) for i in range(n)]


def test_interleaved_solve_cancellation_keeps_completed_batches(monkeypatch) -> None:
    # 4 duties, batch size 1 -> 4 sequential batches. The cancel_event is set
    # only *after* the first batch's solve call returns (not during it, and not
    # via a call-counter, which would also catch the per-batch solve's own
    # internal is_set() checks) -> batch 1 completes cleanly, batch 2 never starts.
    import app.algorithm.solver as solver_mod

    dt = uuid4()
    soldiers = [
        SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)
        for _ in range(4)
    ]
    duties = _line_duties(date(2026, 6, 1), dt, 4)

    cancel_event = threading.Event()
    original = solver_mod._infeasibility_relaxation_chain

    def cancel_after_first_call(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel_event.set()
        return result

    monkeypatch.setattr(solver_mod, "_infeasibility_relaxation_chain", cancel_after_first_call)

    res = solver_mod._interleaved_solve(
        soldiers, duties, [],
        SolverSettings(decomposition="interleaved", interleaved_batch_size=1, batch_time_limit_seconds=10),
        reserve_dist=None, cancel_event=cancel_event,
    )
    assert res.status == "CANCELLED"
    assert 0 < len(res.assignments) < len(duties), (
        "the completed first batch's assignments should be kept, not discarded, "
        "while later (never-run) batches correctly contribute nothing"
    )


def test_decomposed_solve_cancellation_keeps_completed_batches(monkeypatch) -> None:
    # Two duties 44 days apart with a 28-day window -> 2 calendar batches.
    # cancel_event is set only after the first batch's solve returns.
    import app.algorithm.solver as solver_mod

    soldier_ids = [uuid4() for _ in range(3)]
    duty_type_id = uuid4()
    duty_location_id = uuid4()
    soldiers = [
        SoldierInput(id=sid, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=200)
        for sid in soldier_ids
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type_id, duty_location_id=duty_location_id,
                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 1), score_per_day=Decimal("1.00")),
        DutyBlock(id=uuid4(), duty_type_id=duty_type_id, duty_location_id=duty_location_id,
                  start_date=date(2026, 7, 15), end_date=date(2026, 7, 15), score_per_day=Decimal("1.00")),
    ]

    cancel_event = threading.Event()
    original = solver_mod._infeasibility_relaxation_chain

    def cancel_after_first_call(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel_event.set()
        return result

    monkeypatch.setattr(solver_mod, "_infeasibility_relaxation_chain", cancel_after_first_call)

    res = solver_mod._decomposed_solve(
        soldiers, duties, [],
        SolverSettings(batch_window_days=28, decomposition="calendar"),
        reserve_dist=None, cancel_event=cancel_event,
    )
    assert res.status == "CANCELLED"
    assert 0 < len(res.assignments) < len(duties), (
        "the completed first batch's assignments should be kept, not discarded, "
        "while the later (never-run) batch correctly contributes nothing"
    )


def test_effort_round_solve_cancellation_keeps_completed_components(monkeypatch) -> None:
    # Soldier 1 is exempt from dt_b, soldier 2 is exempt from dt_a, so the two
    # (duty, soldier) pairs share no eligibility edge -> 2 disjoint components.
    # cancel_event is set only after the first component's solve returns, same
    # reasoning as the interleaved test above.
    import app.algorithm.solver as solver_mod

    dt_a, dt_b = uuid4(), uuid4()
    soldier_1, soldier_2 = uuid4(), uuid4()
    soldiers = [
        SoldierInput(id=soldier_1, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, exempted_duty_type_ids={dt_b}),
        SoldierInput(id=soldier_2, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, exempted_duty_type_ids={dt_a}),
    ]
    duties = [
        _single_day_duty(date(2026, 6, 1), dt_a, is_reserve=False),
        _single_day_duty(date(2026, 6, 2), dt_b, is_reserve=False),
    ]

    cancel_event = threading.Event()
    original = solver_mod._search_relaxation_ladder

    def cancel_after_first_call(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel_event.set()
        return result

    monkeypatch.setattr(solver_mod, "_search_relaxation_ladder", cancel_after_first_call)

    res = solver_mod._effort_round_solve(
        soldiers, duties, [],
        SolverSettings(round_soldier_count=50, batch_time_limit_seconds=10),
        reserve_dist=None, cancel_event=cancel_event,
    )
    assert res.status == "CANCELLED"
    assert 0 < len(res.assignments) < len(duties), (
        "the completed first component's assignments should be kept, not discarded"
    )


def test_effort_rounds_small_component_single_round() -> None:
    dt = uuid4()
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100) for _ in range(5)]
    duties = _line_duties(date(2026,6,1), dt, 5)
    from app.algorithm.solver import _effort_round_solve
    res = _effort_round_solve(soldiers, duties, [], SolverSettings(round_soldier_count=50, batch_time_limit_seconds=10), reserve_dist=None, cancel_event=None)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert len(res.assignments) == 5
    assert all(not r.startswith("LAST_RESORT") for r in res.relaxed)


def test_effort_rounds_soft_path_two_groups_relaxes_to_full() -> None:
    # Exercises the soft Phase-1 (multi-group) + Phase-2 relaxation path that the
    # Phase-0 hard fast-path bypasses for fully-coverable components.
    # 2 soldiers, round_soldier_count=1 → 2 disjoint groups.
    # 6 real duties on 6 consecutive days, all in one 14-day density window.
    # Base T=2: each soldier covers ≤2 real/window → ≤4 covered at base caps,
    # so Phase 0 (hard ==1 over all 6) is INFEASIBLE → soft rounds run.
    # Phase 2 relaxes T up to 3 → 2 soldiers × 3 = 6 → full coverage.
    dt = uuid4()
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026,1,1),
                             cumulative_score=Decimal(str(i)), active_days=100)
                for i in range(2)]
    duties = _line_duties(date(2026,6,1), dt, 6)
    from app.algorithm.solver import _effort_round_solve
    res = _effort_round_solve(
        soldiers, duties, [],
        SolverSettings(
            decomposition="effort_rounds", round_soldier_count=1,
            T=2, Wt=14, R=6, Wr=14,
            relax_t_ceiling=3, relax_r_ceiling=6,
            batch_time_limit_seconds=10, time_limit_seconds=10,
        ),
        reserve_dist=None, cancel_event=None,
    )
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert len(res.assignments) == 6, (
        f"should fully cover all 6 after Phase-2 relaxation, got {len(res.assignments)}"
    )
    assert any(r.startswith("T→") for r in res.relaxed), (
        f"expected the soft Phase-2 relaxation path to run, relaxed={res.relaxed}"
    )


def test_effort_rounds_two_groups_cover_all() -> None:
    dt = uuid4()
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026,1,1), cumulative_score=Decimal(str(i)), active_days=100) for i in range(4)]
    duties = _line_duties(date(2026,6,1), dt, 8)
    from app.algorithm.solver import _effort_round_solve
    res = _effort_round_solve(soldiers, duties, [], SolverSettings(round_soldier_count=2, batch_time_limit_seconds=10), reserve_dist=None, cancel_event=None)
    assert len(res.assignments) == 8


def test_effort_round_solve_attaches_saturation_clusters_on_shortfall() -> None:
    # 1 soldier, 1 existing commitment covering the same window as 1 unassignable
    # duty (same duty_type both real, T cap of 1 already consumed) — the
    # eligible pool (1 soldier) is fully busy, so the leftover duty must carry
    # a saturation cluster naming the soldier's existing duty type.
    competing_type = uuid4()
    saturated_type = uuid4()
    soldier_id = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    existing = [ExistingAssignment(soldier_id=soldier_id, duty_type_id=competing_type,
                                   start_date=base, end_date=base + timedelta(days=1), is_reserve=False)]
    duties = [_single_day_duty(base, saturated_type, is_reserve=False)]
    from app.algorithm.solver import _effort_round_solve
    res = _effort_round_solve(
        soldiers, duties, existing,
        SolverSettings(T=1, Wt=2, R=1, Wr=2, relax_t_ceiling=1, relax_r_ceiling=1,
                      round_soldier_count=50, batch_time_limit_seconds=10, time_limit_seconds=10),
        reserve_dist=None, cancel_event=None,
    )
    assert len(res.assignments) == 0
    assert len(res.batch_results) == 1
    clusters = res.batch_results[0].saturation_clusters
    assert len(clusters) == 1
    assert clusters[0].free_count == 0
    assert dict(clusters[0].competing_duty_types) == {competing_type: 1}


def test_spreads_duties_evenly_when_soldiers_outnumber_duties() -> None:
    """Regression for the 105%-CV production bug: with uniform effort rates and
    duties < soldiers, the fair split gives everyone at most 1 duty (5 get none,
    unavoidably, since there are only 15 duties for 20 soldiers) — never some
    soldiers at 0 while others get doubled up, which is what a too-weak
    count-spread tiebreaker (count_w) allowed before this fix."""
    duty_type = uuid4()
    loc = uuid4()
    soldiers = [
        _eff_soldier(uuid4(), offset=0, per_milli=1000)
        for _ in range(20)
    ]
    base = date(2026, 6, 1)
    duties = []
    for i in range(10):
        d = base + timedelta(days=i * 6)
        duties.append(DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                                 start_date=d, end_date=d + timedelta(days=1), score_per_day=Decimal("4.00")))
    for i in range(5):
        d = base + timedelta(days=i * 11)
        duties.append(DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=loc,
                                 start_date=d, end_date=d + timedelta(days=8), score_per_day=Decimal("4.00")))

    settings = SolverSettings(T=8, Wt=14, R=15, Wr=28, time_limit_seconds=5,
                               decomposition="none", batching_enabled=False)
    result = solve(soldiers, duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 15

    counts: dict = {s.id: 0 for s in soldiers}
    for a in result.assignments:
        counts[a.soldier_id] += 1
    counts_list = sorted(counts.values())

    assert max(counts_list) <= 1, f"no soldier should be doubled up while another sits idle, got {counts_list}"
    assert counts_list.count(0) == 5, f"exactly 5 soldiers should be idle (15 duties / 20 soldiers), got {counts_list}"


def test_eligible_pairs_subtree_match() -> None:
    """A soldier in a sub-team under a scoped node is eligible (subtree match,
    not exact match)."""
    from app.algorithm.solver import _eligible_pairs

    root = uuid4()
    child = uuid4()
    s_in_subtree = uuid4()
    s_outside = uuid4()
    s_unassigned = uuid4()
    dt = uuid4()

    soldiers = [
        SoldierInput(id=s_in_subtree, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=child, path_ids=[root, child]),
        SoldierInput(id=s_outside, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=uuid4(), path_ids=[uuid4()]),
        SoldierInput(id=s_unassigned, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=None, path_ids=[]),
    ]
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                      score_per_day=Decimal("1"), eligible_node_ids=[root])

    pairs = _eligible_pairs(soldiers, [duty])
    eligible_soldier_idxs = {si for _, si in pairs}
    assert eligible_soldier_idxs == {0}  # only s_in_subtree (idx 0)


def test_solve_excludes_soldier_outside_scope() -> None:
    """End-to-end: a duty scoped to one branch is never assigned to a soldier
    from a different branch, even if that soldier is otherwise idle."""
    root_a = uuid4()
    root_b = uuid4()
    s_in_scope = uuid4()
    s_out_of_scope = uuid4()
    dt = uuid4()
    loc = uuid4()

    soldiers = [
        SoldierInput(id=s_in_scope, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=root_a, path_ids=[root_a]),
        SoldierInput(id=s_out_of_scope, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=root_b, path_ids=[root_b]),
    ]
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                      score_per_day=Decimal("1"), eligible_node_ids=[root_a])

    result = solve(soldiers, [duty], [], SolverSettings(time_limit_seconds=10, batching_enabled=False))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].soldier_id == s_in_scope


def test_solve_subtree_match_end_to_end() -> None:
    """A soldier in a sub-team under the scoped node is assignable; one outside
    the subtree, with no other duties competing, is not."""
    root = uuid4()
    child = uuid4()
    s_in_subtree = uuid4()
    s_outside = uuid4()
    dt = uuid4()
    loc = uuid4()

    soldiers = [
        SoldierInput(id=s_in_subtree, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=child, path_ids=[root, child]),
        SoldierInput(id=s_outside, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=uuid4(), path_ids=[uuid4()]),
    ]
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                      score_per_day=Decimal("1"), eligible_node_ids=[root])

    result = solve(soldiers, [duty], [], SolverSettings(time_limit_seconds=10, batching_enabled=False))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].soldier_id == s_in_subtree


def test_node_quota_exact_assignment():
    """Each DutyBlock represents one slot of a shift (matching how
    algorithm_bridge.py expands shift.required_count into one DutyBlock per
    slot, each with its own id — see DutyBlock(...) construction loops in
    app/services/algorithm_bridge.py). A slot's node_quotas reserves that
    specific slot for soldiers under a given hierarchy node; build_model's
    coverage constraint already forces exactly one assignee per slot
    (sum(vars_for_d) == 1), so a per-slot quota dict must have exactly one
    node with count=1 — not an aggregate split across multiple slots sharing
    the same dict, which would be self-contradictory (sum == 1 from coverage
    vs. sum == 2/3 from the quota, on the very same slot). Here, 2 of the 5
    slots are reserved for node_a and 3 for node_b, forcing an exact 2/3
    split across the shift as a whole."""
    node_a = uuid.uuid4()
    node_b = uuid.uuid4()
    duty_type = uuid.uuid4()
    location = uuid.uuid4()

    soldiers = [
        SoldierInput(id=uuid.uuid4(), enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
                     active_days=100, hierarchy_node_id=node_a, path_ids=[node_a])
        for _ in range(2)
    ] + [
        SoldierInput(id=uuid.uuid4(), enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
                     active_days=100, hierarchy_node_id=node_b, path_ids=[node_b])
        for _ in range(3)
    ]

    def _slot(node_id: uuid.UUID) -> DutyBlock:
        return DutyBlock(
            id=uuid.uuid4(), duty_type_id=duty_type, duty_location_id=location,
            start_date=date(2024, 6, 1), end_date=date(2024, 6, 1),
            score_per_day=Decimal("1.0"),
            node_quotas={node_id: 1},
        )

    duties = [_slot(node_a) for _ in range(2)] + [_slot(node_b) for _ in range(3)]

    model, x = build_model(soldiers, duties, [], SolverSettings(time_limit_seconds=5))
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assigned_a = sum(
        1 for (di, si), var in x.items()
        if soldiers[si].hierarchy_node_id == node_a and solver.Value(var) == 1
    )
    assigned_b = sum(
        1 for (di, si), var in x.items()
        if soldiers[si].hierarchy_node_id == node_b and solver.Value(var) == 1
    )
    assert assigned_a == 2
    assert assigned_b == 3


def test_node_quota_soft_coverage_leaves_unfillable_duty_unassigned():
    """Under coverage='soft', a duty carrying a node_quotas entry must still be
    leave-able entirely unfilled when the only soldier who could satisfy the
    quota is actually unavailable (blocked by an overlapping existing
    assignment) — the quota's `== count` constraint must not override the
    soft escape valve and force INFEASIBLE. The quota's matching_vars is
    non-empty (the soldier is under the quota node and otherwise eligible),
    but the no-overlap constraint pins that var to 0, so satisfying
    `sum(matching_vars) == 1` unconditionally would be globally infeasible.
    With the fix, the duty is simply left unassigned instead."""
    node_quota = uuid.uuid4()
    duty_type = uuid.uuid4()
    location = uuid.uuid4()
    soldier_id = uuid.uuid4()

    soldier = SoldierInput(
        id=soldier_id, enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
        active_days=100, hierarchy_node_id=node_quota, path_ids=[node_quota],
    )
    # Note: both DutyBlock and ExistingAssignment date ranges are half-open
    # ([start, end)), so end_date must be the day *after* the covered day for
    # the range to actually include 2024-06-01.
    duty = DutyBlock(
        id=uuid.uuid4(), duty_type_id=duty_type, duty_location_id=location,
        start_date=date(2024, 6, 1), end_date=date(2024, 6, 2),
        score_per_day=Decimal("1.0"),
        eligible_node_ids=[node_quota],
        node_quotas={node_quota: 1},
    )
    # Soldier already has a published assignment covering the same day, so
    # the no-overlap constraint forces their var for this duty to 0.
    existing = [
        ExistingAssignment(
            soldier_id=soldier_id, duty_type_id=duty_type,
            start_date=date(2024, 6, 1), end_date=date(2024, 6, 2),
        )
    ]

    model, x = build_model(
        [soldier], [duty], existing, SolverSettings(time_limit_seconds=5), coverage="soft",
    )
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert all(solver.Value(var) == 0 for var in x.values())


def test_node_quota_soft_coverage_enforces_quota_when_filled():
    """Under coverage='soft', if a quota'd duty IS filled, the quota must
    still be honored exactly — the soft escape valve only relaxes the
    'must be covered' requirement, not the quota itself once covered.
    Two soldiers are eligible; only one is under the quota node, so the
    solver is forced to pick the matching one (or leave unassigned)."""
    node_quota = uuid.uuid4()
    node_other = uuid.uuid4()
    root = uuid.uuid4()
    duty_type = uuid.uuid4()
    location = uuid.uuid4()

    s_match = SoldierInput(
        id=uuid.uuid4(), enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
        active_days=100, hierarchy_node_id=node_quota, path_ids=[root, node_quota],
    )
    s_other = SoldierInput(
        id=uuid.uuid4(), enrolled_at=date(2024, 1, 1), cumulative_score=Decimal(0),
        active_days=100, hierarchy_node_id=node_other, path_ids=[root, node_other],
    )
    duty = DutyBlock(
        id=uuid.uuid4(), duty_type_id=duty_type, duty_location_id=location,
        start_date=date(2024, 6, 1), end_date=date(2024, 6, 1),
        score_per_day=Decimal("1.0"),
        eligible_node_ids=[root],
        node_quotas={node_quota: 1},
    )

    model, x = build_model(
        [s_match, s_other], [duty], [], SolverSettings(time_limit_seconds=5), coverage="soft",
    )
    # Soft coverage alone doesn't require the duty to be filled; force it here
    # so we can verify the quota still binds correctly when it IS filled.
    model.Add(sum(x.values()) == 1)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    assigned = {si for (di, si), var in x.items() if solver.Value(var) == 1}
    # Forced to fill, but the quota forbids picking the non-matching soldier
    # (index 1) — only the matching soldier (index 0) can satisfy it.
    assert assigned == {0}
