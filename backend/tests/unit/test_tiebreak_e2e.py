"""
End-to-end correctness and fairness tests for SolverSettings.tiebreak_mode.

test_fairness_batching.py covers the specific bug and the apply_tiebreak_
objective tier mechanics in isolation (hand-engineered ties). This file
covers the full solve() pipeline (interleaved batching, density caps,
eligibility, multi-batch carry-forward) across randomised scenarios, to
answer two separate questions:

CORRECTNESS — does enabling tiebreak_mode="range" ever produce an INVALID
solution (duplicate assignment, density-cap violation, ineligible
assignment, dropped coverage)? It must not: stage 2 only ever re-solves the
SAME constraint set with a different objective, so every invariant stage 1
already guaranteed should still hold.

FAIRNESS — does tiebreak_mode="range" actually reduce variance in practice?
IMPORTANT CALIBRATION NOTE: across randomised multi-batch scenarios, "range"
does NOT monotonically improve every single run. Within any one batch,
stage 2 mathematically cannot do worse than that batch's own stage-1 result
(it only replaces stage 1 if it finds an equal-or-better tie-broken
solution). But improving one batch changes the effort_offset carried into
later batches, which can occasionally leave a LATER batch in a position
where ITS tie happens to resolve less favourably than it would have
otherwise — so the cumulative, end-of-run effect is a statistical
improvement, not a per-run guarantee. The calibrated scenarios below therefore
assert the aggregate directional improvement. Each mode receives a deep copy of
the same scenario so IDs and all solver inputs are identical.
"""
from __future__ import annotations

import copy
import random
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.algorithm.solver import solve
from app.algorithm.types import EFFORT_SCALE, DutyBlock, SoldierInput, SolverSettings


def _effort(cumulative_score: Decimal, active_days: int) -> dict:
    return {
        "effort_offset": int(cumulative_score * EFFORT_SCALE / active_days),
        "effort_per_milli": EFFORT_SCALE // (active_days * 1000),
    }


def _duties(m: int, rng: random.Random, duty_types: list[uuid.UUID], gap_days: int = 2) -> list[DutyBlock]:
    start = date(2027, 1, 1)
    return [
        DutyBlock(
            id=uuid.uuid4(),
            duty_type_id=rng.choice(duty_types),
            duty_location_id=uuid.uuid4(),
            start_date=start + timedelta(days=i * gap_days),
            end_date=start + timedelta(days=i * gap_days + 1),
            score_per_day=Decimal(str(round(rng.uniform(0.5, 3.0), 1))),
        )
        for i in range(m)
    ]


def _soldiers(n: int, rng: random.Random, days: int = 100) -> list[SoldierInput]:
    out = []
    for _ in range(n):
        cum = Decimal(str(round(rng.uniform(0, 150), 2)))
        out.append(SoldierInput(
            id=uuid.uuid4(), enrolled_at=date(2024, 1, 1),
            cumulative_score=cum, active_days=days, **_effort(cum, days),
        ))
    return out


def _settings(mode: str, **overrides) -> SolverSettings:
    base = dict(
        T=7, Wt=14, R=15, Wr=28, alpha=Decimal("1.0"),
        decomposition="interleaved", batching_enabled=True,
        interleaved_batch_size=10, batch_time_limit_seconds=15,
        tiebreak_mode=mode, tiebreak_time_limit_seconds=10, seed=1,
    )
    base.update(overrides)
    return SolverSettings(**base)


def _duty_days(d: DutyBlock) -> list[date]:
    dt = d.start_date
    out = []
    while dt < d.end_date:
        out.append(dt)
        dt += timedelta(days=1)
    return out


def _max_window_count(days: list[date], window: int) -> int:
    """Max number of `days` falling within any `window`-day sliding window."""
    days = sorted(days)
    best = 0
    for start in days:
        end = start + timedelta(days=window - 1)
        best = max(best, sum(1 for d in days if start <= d <= end))
    return best


# ─── Correctness ───────────────────────────────────────────────────────────


CORRECTNESS_CASES = [
    (10, 30, 1001),
    (15, 40, 1002),
    (20, 50, 1003),
]


@pytest.mark.parametrize("n,m,seed", CORRECTNESS_CASES)
def test_range_mode_preserves_invariants_and_coverage(n, m, seed):
    """Range mode preserves hard constraints and stage-1 coverage."""
    rng = random.Random(seed)
    duty_types = [uuid.uuid4() for _ in range(3)]
    soldiers = _soldiers(n, rng)
    duties = _duties(m, rng, duty_types)

    range_soldiers = copy.deepcopy(soldiers)
    range_result = solve(range_soldiers, copy.deepcopy(duties), [], _settings("range"))
    off_result = solve(copy.deepcopy(soldiers), copy.deepcopy(duties), [], _settings("off"))
    assert range_result.status in ("OPTIMAL", "FEASIBLE")
    assert off_result.status in ("OPTIMAL", "FEASIBLE")

    duty_ids = [a.duty_id for a in range_result.assignments]
    assert len(duty_ids) == len(set(duty_ids)), "a duty was assigned to more than one soldier"

    duty_by_id = {d.id: d for d in duties}
    days_by_soldier: dict[uuid.UUID, list[date]] = {}
    for a in range_result.assignments:
        days_by_soldier.setdefault(a.soldier_id, []).extend(_duty_days(duty_by_id[a.duty_id]))
    settings = _settings("range")
    for soldier_id, days in days_by_soldier.items():
        worst = _max_window_count(days, settings.Wr)
        assert worst <= settings.R, (
            f"soldier {soldier_id} has {worst} duty-days in a {settings.Wr}-day "
            f"window, exceeding R={settings.R}"
        )

    assert len(range_result.assignments) == len(off_result.assignments), (
        f"'range' assigned {len(range_result.assignments)} duties vs 'off''s "
        f"{len(off_result.assignments)} — tiebreak should never change coverage"
    )


def test_range_mode_never_assigns_exempted_duty_types():
    """Range mode preserves duty-type eligibility."""
    rng = random.Random(2001)
    duty_types = [uuid.uuid4() for _ in range(3)]
    soldiers = _soldiers(12, rng)
    for s in soldiers[:6]:
        s.exempted_duty_type_ids = {duty_types[0]}
    duties = _duties(36, rng, duty_types)

    result = solve(soldiers, duties, [], _settings("range"))
    assert result.status in ("OPTIMAL", "FEASIBLE")

    duty_by_id = {d.id: d for d in duties}
    soldier_by_id = {s.id: s for s in soldiers}
    for a in result.assignments:
        duty_type = duty_by_id[a.duty_id].duty_type_id
        exempted = soldier_by_id[a.soldier_id].exempted_duty_type_ids
        assert duty_type not in exempted, (
            f"soldier {a.soldier_id} was assigned duty_type {duty_type}, "
            f"which they're exempted from"
        )

# ─── Fairness ───────────────────────────────────────────────────────────────


FAIRNESS_CASES = [
    (8, 16, 1), (8, 16, 2), (8, 16, 3), (8, 16, 4), (8, 16, 5),
    (10, 30, 1), (10, 30, 2), (10, 30, 3), (10, 30, 4), (10, 30, 5),
    (15, 40, 1), (15, 40, 2), (15, 40, 3), (15, 40, 4), (15, 40, 5),
    (20, 50, 1), (20, 50, 2), (20, 50, 3), (20, 50, 4), (20, 50, 5),
]


def _spread(result, soldiers) -> int:
    counts = Counter(a.soldier_id for a in result.assignments)
    vals = [counts.get(s.id, 0) for s in soldiers]
    return max(vals) - min(vals)


def _scenario_spreads(case: tuple[int, int, int]) -> tuple[int, int]:
    """Solve one reproducible, identical scenario in both modes."""
    n, m, seed = case

    def stable_id(kind: str, index: int) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"justice:tiebreak:{n}:{m}:{seed}:{kind}:{index}")

    rng = random.Random(seed)
    duty_types = [stable_id("duty-type", i) for i in range(3)]
    soldiers = _soldiers(n, rng)
    duties = _duties(m, rng, duty_types)
    for i, soldier in enumerate(soldiers):
        soldier.id = stable_id("soldier", i)
    for i, duty in enumerate(duties):
        duty.id = stable_id("duty", i)
        duty.duty_location_id = stable_id("location", i)

    spreads = []
    for mode in ("off", "range"):
        mode_soldiers = copy.deepcopy(soldiers)
        result = solve(mode_soldiers, copy.deepcopy(duties), [], _settings(mode))
        assert result.status in ("OPTIMAL", "FEASIBLE")
        spreads.append(_spread(result, mode_soldiers))
    return spreads[0], spreads[1]


@pytest.mark.slow
def test_range_mode_improves_average_spread_across_scenarios():
    """'range' improves average spread over the same randomised scenarios.

    Each CP-SAT solve is single-threaded, so independent scenario pairs run in
    a small thread pool. OR-Tools releases the GIL while solving; this preserves
    the aggregate assertion while avoiding one long serial pytest tail.
    """
    with ThreadPoolExecutor(max_workers=4) as executor:
        spreads = list(executor.map(_scenario_spreads, FAIRNESS_CASES))

    off_spreads = [off for off, _ in spreads]
    range_spreads = [range_ for _, range_ in spreads]
    mean_off = sum(off_spreads) / len(off_spreads)
    mean_range = sum(range_spreads) / len(range_spreads)

    assert mean_range < mean_off, (
        f"'range' should reduce average spread across {len(FAIRNESS_CASES)} "
        f"scenarios; got mean_off={mean_off:.2f}, mean_range={mean_range:.2f} "
        f"(off={off_spreads}, range={range_spreads})"
    )

def test_range_mode_recovers_known_achievable_split():
    """The deterministic, exactly-calibrated case from test_fairness_batching
    .py: 4 identical soldiers splitting an evenly-divisible total of 64
    duties should land on exactly [16, 16, 16, 16] under 'range', not the
    [15, 15, 17, 17] 'off' settles for. Kept here too (not just in the unit
    test) as the canonical, deterministic proof point backing the
    statistical claim above."""
    duty_type = uuid.uuid4()

    def soldier(effort_per_milli: int) -> SoldierInput:
        return SoldierInput(
            id=uuid.uuid4(), enrolled_at=date(2025, 1, 1),
            cumulative_score=Decimal("0"), active_days=200,
            effort_offset=0, effort_per_milli=effort_per_milli,
        )

    def duty(start: date) -> DutyBlock:
        return DutyBlock(
            id=uuid.uuid4(), duty_type_id=duty_type, duty_location_id=uuid.uuid4(),
            start_date=start, end_date=start, score_per_day=Decimal("1.0"),
        )

    tied = [soldier(1000) for _ in range(4)]
    heavy = [soldier(4000) for _ in range(2)]
    duties = [duty(date(2027, 1, 1) + timedelta(days=i)) for i in range(72)]
    settings = _settings(
        "range", T=200, Wt=200, R=200, Wr=200,
        interleaved_batch_size=6, batch_time_limit_seconds=10,
    )

    result = solve(tied + heavy, duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    counts = Counter(a.soldier_id for a in result.assignments)
    assert sorted(counts.get(s.id, 0) for s in tied) == [16, 16, 16, 16]
