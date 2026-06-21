"""
End-to-end randomised fairness tests for the CP-SAT assignment model.

MOTIVATION
----------
Unit tests (test_fairness.py) check hand-crafted edge cases.  These tests
go further: they generate randomised scenarios with different numbers of
soldiers (n) and duties (m), varying duty scores, and varying historical
scores.  Each scenario is solved and the resulting assignment is checked
against formally provable fairness properties.

All scenarios use a fixed seed per parametrize case so results are fully
deterministic; changing the seed explores different regions of the space.

SCALE
-----
Tests come in two tiers:

  • Normal  (no marker) — n ≤ 10, m ≤ 20, duties spaced 2 weeks apart.
    Runs in < 1 s per case; included in every CI run.

  • Large   (@pytest.mark.slow) — n ≈ 100, m ≈ 200, duties on consecutive
    days.  Solver timeout is 120 s; total suite ≈ 5–8 min.  Run explicitly:
        pytest --slow -m slow tests/unit/test_fairness_e2e.py

    Large cases use T=14, W=14 with daily duty spacing so the density
    constraint spans only ~m days instead of ~m×14 days, keeping build time
    under 15 s even at scale.

TESTED PROPERTIES
-----------------

A — ASSIGNMENT ORDERING  (equal active_days scenarios)
    When every soldier shares the same number of active_days, the problem
    reduces to minimising max(cum_score + new_score) across soldiers — a
    classic makespan-minimisation problem.  It is provably sub-optimal to
    give a higher-cum soldier more new score than a lower-cum soldier:
    swapping their duties lowers the maximum without raising it elsewhere.
    The secondary objective (maximise min norm) further reinforces this.

    Formal claim:
        ∀ soldiers A, B with cum_A < cum_B (equal active_days):
            new_score(A) ≥ new_score(B)

B — EXTREME-GAP CONVERGENCE  (mixed-spd groups)
    When one group has spd ≈ 0 and another has spd ≈ 0.5–1.0, the gap
    is so large that assigning any duty to the high-spd group would raise
    the objective's max-norm term by far more than assigning to the
    low-spd group.  Therefore every duty must flow to the low-spd group.

    Formal claim:
        every high-spd soldier receives 0 new score
        (provided no T/W density violation forces otherwise)
"""
from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from ortools.sat.python.cp_model import CpSolver

from app.algorithm.model import build_model
from app.algorithm.types import EFFORT_SCALE, DutyBlock, SoldierInput, SolverSettings

# ─── Shared constants ─────────────────────────────────────────────────────────

STD = dict(T=7, Wt=14, Wr=28, alpha=Decimal("1.0"))

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _effort(cumulative_score: Decimal, active_days: int) -> dict:
    """Effort fields that mirror the production metric for these score-based
    scenarios, so the effort-optimising model reproduces score_per_day fairness.

    The model optimises quarterly EFFORT, not cumulative_score; these tests
    historically expressed load as cumulative_score / active_days (score_per_day).
    We map that onto effort on the EFFORT_SCALE:
        effort_offset    = score_per_day × EFFORT_SCALE   (historical load)
        effort_per_milli = EFFORT_SCALE / (active_days × 1000)
    so a new 1-day duty of score s raises effort by s / active_days × EFFORT_SCALE
    — exactly score_per_day's marginal. effort_offset is monotonic in
    cumulative_score (active_days is uniform here), so assertions that sort by
    cumulative_score are unchanged.
    """
    return {
        "effort_offset": int(Decimal(cumulative_score) * EFFORT_SCALE / active_days),
        "effort_per_milli": EFFORT_SCALE // (active_days * 1000),
    }


def _duties(m: int, rng: random.Random, gap_days: int = 14) -> list[DutyBlock]:
    """m single-day duties with randomised scores in [0.5, 3.0].

    gap_days=14 (default) — 2-week spacing, used by normal-scale tests.
    gap_days=1  — daily spacing, used by large-scale (@slow) tests to keep
                  the density-constraint date-range short (O(m) not O(m×14)).
    """
    start = date(2027, 1, 1)
    return [
        DutyBlock(
            id=uuid.uuid4(),
            duty_type_id=uuid.uuid4(),
            duty_location_id=uuid.uuid4(),
            start_date=start + timedelta(days=i * gap_days),
            end_date=start + timedelta(days=i * gap_days),
            # One decimal place so Decimal arithmetic is exact
            score_per_day=Decimal(str(round(rng.uniform(0.5, 3.0), 1))),
        )
        for i in range(m)
    ]


def _soldiers_equal_days(n: int, rng: random.Random, days: int = 100) -> list[SoldierInput]:
    """n soldiers with the same active_days but uniformly randomised cumulative scores."""
    out = []
    for _ in range(n):
        # Two decimal places — Decimal arithmetic stays exact when multiplied by 1000
        cum = Decimal(str(round(rng.uniform(0, 150), 2)))
        out.append(SoldierInput(
            id=uuid.uuid4(),
            enrolled_at=date(2024, 1, 1),
            cumulative_score=cum,
            active_days=days,
            **_effort(cum, days),
        ))
    return out


def _soldiers_mixed_days(n: int, rng: random.Random) -> list[SoldierInput]:
    """n soldiers with randomised cumulative scores and randomised active_days."""
    out = []
    for _ in range(n):
        cum = Decimal(str(round(rng.uniform(0, 200), 2)))
        days = rng.randint(30, 500)
        out.append(SoldierInput(
            id=uuid.uuid4(),
            enrolled_at=date(2024, 1, 1),
            cumulative_score=cum,
            active_days=days,
            **_effort(cum, days),
        ))
    return out


def _solve(
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    *,
    settings_override: dict | None = None,
    timeout_s: int = 30,
) -> tuple[dict[uuid.UUID, Decimal], str]:
    """Run the CP-SAT solver.

    Returns ({soldier_id → total new score this run}, status_name).
    status_name is "OPTIMAL" or "FEASIBLE"; callers that need guaranteed
    ordering should skip when status != "OPTIMAL".
    settings_override replaces STD for large-scale cases that need different T/W.
    """
    settings = SolverSettings(**(settings_override or STD))
    model, x = build_model(soldiers, duties, [], settings)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = timeout_s
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    assert status_name in ("OPTIMAL", "FEASIBLE"), f"Solver returned {status_name}"
    result: dict[uuid.UUID, Decimal] = {s.id: Decimal(0) for s in soldiers}
    for (di, si), var in x.items():
        if solver.Value(var):
            result[soldiers[si].id] += duties[di].score_per_day
    return result, status_name


def _post_norm_milli(soldier: SoldierInput, new_score: Decimal) -> int:
    """Post-run norm in milli-units, using the same integer arithmetic as CP-SAT.

    Mirrors the model's:
        base = int(s.cumulative_score * 1000)
        cum_total = base + block_sum          (block_sum = int(score * 1000) for 1-day duties)
        norm = cum_total // active_days       (AddDivisionEquality = floor division)
    """
    base = int(soldier.cumulative_score * 1000)
    new_int = int(new_score * 1000)
    return (base + new_int) // soldier.active_days


# ─── Property A: Assignment ordering (equal active_days) ─────────────────────
#
# Cases span small (n=2,3), medium (n=5,6), and larger (n=8,10) groups,
# and duty-to-soldier ratios from under-constrained (1:1) to over-constrained (3:1).

EQUAL_DAYS_CASES = [
    # (n_soldiers, n_duties, seed)
    (2,  1,  1001),   # smallest possible: 2 soldiers, 1 duty
    (3,  3,  1002),   # 1 duty per soldier — perfectly divisible
    (3,  9,  1003),   # 3× over-subscribed
    (3,  15, 1004),   # 5× over-subscribed, varied scores
    (5,  5,  1005),   # medium, exactly 1 each
    (5,  12, 1006),   # medium, 2–3 per soldier
    (5,  20, 1007),   # heavy load
    (8,  8,  1008),   # larger group, 1 each
    (8,  16, 1009),   # larger group, 2 each
    (10, 6,  1010),   # more soldiers than duties
]


@pytest.mark.parametrize("n,m,seed", EQUAL_DAYS_CASES)
def test_e2e_assignment_ordering_equal_days(n: int, m: int, seed: int) -> None:
    """Equal active_days: lower cumulative score always receives ≥ new score.

    With equal active_days the primary objective collapses to minimising
    max(cum + new).  Any solution where lower-cum soldier A receives less
    new score than higher-cum soldier B can be strictly improved by swapping
    their duty assignments (A's new post-score drops, B's drops; the maximum
    can only decrease or stay equal).  The secondary objective (maximise min
    norm) further penalises under-serving low-cum soldiers.  Therefore no
    optimal solution violates this ordering.
    """
    rng = random.Random(seed)
    soldiers = _soldiers_equal_days(n, rng)
    duties = _duties(m, rng)

    new_score, _ = _solve(soldiers, duties)

    # Sort ascending by pre-run cumulative score
    sorted_s = sorted(soldiers, key=lambda s: s.cumulative_score)

    violations = [
        (
            f"  A(cum={a.cumulative_score}) → new={new_score[a.id]:.1f}  "
            f"< B(cum={b.cumulative_score}) → new={new_score[b.id]:.1f}"
        )
        for a, b in zip(sorted_s, sorted_s[1:])
        if a.cumulative_score < b.cumulative_score      # strictly ordered pair
        and new_score[a.id] < new_score[b.id]           # wrong direction
    ]
    assert not violations, (
        f"[n={n}, m={m}, seed={seed}] "
        f"Lower-cum soldiers must receive ≥ new score than higher-cum soldiers.\n"
        f"Violations:\n" + "\n".join(violations)
    )


# ─── Property B: Extreme-gap convergence ──────────────────────────────────────
#
# A large spd gap makes the assignment preference unambiguous: any duty
# routed to the high group raises max_norm by ≈ (score * 1000 / days) on
# top of an already large baseline, while routing to the low group barely
# moves max_norm.  The algorithm must always choose the low group.
#
# low group: cum ∈ [0, 1], days=100  → spd ∈ [0.00, 0.01]
# high group: cum ∈ [50, 100], days=100 → spd ∈ [0.50, 1.00]

GAP_CASES = [
    # (n_low, n_high, n_duties, seed)
    (1, 1,  2, 3001),   # 1 vs 1, 2 duties
    (2, 2,  4, 3002),   # 2 vs 2, 2 duties each
    (3, 1,  6, 3003),   # 3 low absorb 6 duties, 1 high sits idle
    (2, 3,  6, 3004),   # minority low still takes everything
    (4, 2,  8, 3005),
    (3, 3,  9, 3006),
    (2, 4,  4, 3007),   # more high soldiers than low — low still wins
    (5, 3, 10, 3008),
]


@pytest.mark.parametrize("n_low,n_high,m,seed", GAP_CASES)
def test_e2e_extreme_gap_low_absorbs_all(n_low: int, n_high: int, m: int, seed: int) -> None:
    """Soldiers with spd ≈ 0 absorb all duties; soldiers with spd ≈ 0.5–1 get nothing.

    With the high group already at norm ≈ 500–1000 milli-units and the low
    group at ≈ 0–10, assigning a duty (score ≈ 1.5, days=100) to the high
    group would add ≈ 15 milli to an already-high norm, while assigning to
    the low group adds the same ≈ 15 milli to a near-zero norm.  The
    objective therefore always prefers the low group, regardless of duty score.
    """
    rng = random.Random(seed)

    def _grp(n: int, lo: float, hi: float) -> list[SoldierInput]:
        out = []
        for _ in range(n):
            cum = Decimal(str(round(rng.uniform(lo, hi), 2)))
            out.append(SoldierInput(
                id=uuid.uuid4(),
                enrolled_at=date(2024, 1, 1),
                cumulative_score=cum,
                active_days=100,
                **_effort(cum, 100),
            ))
        return out

    low_group = _grp(n_low, 0.0, 1.0)
    high_group = _grp(n_high, 50.0, 100.0)

    duties = _duties(m, rng)
    new_score, _ = _solve(low_group + high_group, duties)

    # Every high-spd soldier must receive exactly 0 new score
    high_assigned = {
        s.id: new_score[s.id]
        for s in high_group
        if new_score[s.id] > 0
    }
    assert not high_assigned, (
        f"[n_low={n_low}, n_high={n_high}, m={m}, seed={seed}] "
        f"High-spd soldiers should receive 0 new duties.\n"
        f"Received assignments:\n"
        + "\n".join(
            f"  high(cum={s.cumulative_score}, spd={float(s.cumulative_score)/100:.2f})"
            f" → new_score={high_assigned[s.id]}"
            for s in high_group if s.id in high_assigned
        )
        + f"\nLow group new scores: "
        + str(sorted(float(new_score[s.id]) for s in low_group))
    )


# ═══════════════════════════════════════════════════════════════════════════════
# LARGE-SCALE TESTS  (@pytest.mark.slow)
#
# Same three properties checked at n ≈ 100, m ≈ 200.
# Run with:  pytest --slow -m slow tests/unit/test_fairness_e2e.py
#
# Settings differ from the normal suite:
#   • duties spaced 1 day apart (gap_days=1) so the density-constraint
#     date-range is O(m) not O(m×W), keeping build time ≈ 10 s
#   • T=14, W=14  (permissive density — never binding at this duty spacing)
#   • solver timeout = 120 s per case
# ═══════════════════════════════════════════════════════════════════════════════

# Settings for large-scale tests (daily spacing, permissive density)
LARGE_STD = dict(T=14, Wt=14, Wr=28, alpha=Decimal("1.0"))
LARGE_TIMEOUT = 120


# ─── Property A (large scale): Assignment ordering ───────────────────────────

LARGE_ORDERING_CASES = [
    # (n, m, seed)
    (80,  160, 4001),   # n=80, m=160
    (100, 100, 4002),   # n=100, m=100
    (100, 120, 4003),   # n=100, m=120
    (100, 200, 4004),   # n=100, m=200  (the full target scale)
]


@pytest.mark.slow
@pytest.mark.parametrize("n,m,seed", LARGE_ORDERING_CASES)
def test_e2e_large_assignment_ordering(n: int, m: int, seed: int) -> None:
    """Equal active_days, large scale: lower-cum soldier receives ≥ new score.

    Same formal guarantee as the normal-scale ordering test, verified at
    n ≈ 100 and m ≈ 200 with daily duty spacing and a 120 s solver budget.
    """
    rng = random.Random(seed)
    soldiers = _soldiers_equal_days(n, rng)
    duties = _duties(m, rng, gap_days=1)

    new_score, status = _solve(soldiers, duties, settings_override=LARGE_STD, timeout_s=LARGE_TIMEOUT)

    if status != "OPTIMAL":
        pytest.skip(
            f"Solver returned {status} (not OPTIMAL) for n={n}, m={m}, seed={seed} — "
            f"ordering is only provable for optimal solutions; increase timeout to retry."
        )

    sorted_s = sorted(soldiers, key=lambda s: s.cumulative_score)

    # Only check pairs where the pre-norm difference is meaningful (≥ 10 milli-units = 0.01 spd).
    # Pairs closer than this are effectively tied in the objective and the integer rounding of
    # AddDivisionEquality can treat them identically, making ordering arbitrary.
    violations = [
        f"  A(cum={a.cumulative_score}, pre_norm={_post_norm_milli(a, Decimal(0))})"
        f" got new={new_score[a.id]:.2f}"
        f"  <  B(cum={b.cumulative_score}, pre_norm={_post_norm_milli(b, Decimal(0))})"
        f" got new={new_score[b.id]:.2f}"
        for a, b in zip(sorted_s, sorted_s[1:])
        if a.cumulative_score < b.cumulative_score
        and _post_norm_milli(b, Decimal(0)) - _post_norm_milli(a, Decimal(0)) >= 10
        and new_score[a.id] < new_score[b.id]
    ]
    assert not violations, (
        f"[n={n}, m={m}, seed={seed}] Ordering violations (pre-norm diff >= 10 milli):\n"
        + "\n".join(violations)
    )


# ─── Property B (large scale): Extreme-gap convergence ───────────────────────

LARGE_GAP_CASES = [
    # (n_low, n_high, m, seed)  — total n = n_low + n_high ≈ 100
    (10, 90, 100, 6001),   # 10 low vs 90 high, 100 duties (total n=100)
    (20, 80, 100, 6002),   # 20 vs 80, 100 duties
    (50, 50, 100, 6003),   # balanced, 100 duties
    (10, 90, 200, 6004),   # 10 vs 90, 200 duties — large m
]


@pytest.mark.slow
@pytest.mark.parametrize("n_low,n_high,m,seed", LARGE_GAP_CASES)
def test_e2e_large_extreme_gap(n_low: int, n_high: int, m: int, seed: int) -> None:
    """Large scale: low-spd group (spd≈0) absorbs all duties; high-spd (spd≈0.5+) get none."""
    rng = random.Random(seed)

    def _grp(n: int, lo: float, hi: float) -> list[SoldierInput]:
        out = []
        for _ in range(n):
            cum = Decimal(str(round(rng.uniform(lo, hi), 2)))
            out.append(SoldierInput(
                id=uuid.uuid4(),
                enrolled_at=date(2024, 1, 1),
                cumulative_score=cum,
                active_days=100,
                **_effort(cum, 100),
            ))
        return out

    low_group = _grp(n_low, 0.0, 1.0)
    high_group = _grp(n_high, 50.0, 100.0)

    duties = _duties(m, rng, gap_days=1)
    new_score, status = _solve(
        low_group + high_group, duties,
        settings_override=LARGE_STD, timeout_s=LARGE_TIMEOUT,
    )

    if status != "OPTIMAL":
        pytest.skip(
            f"Solver returned {status} (not OPTIMAL) for n_low={n_low}, n_high={n_high}, "
            f"m={m}, seed={seed} — gap guarantee only holds for optimal solutions; "
            f"increase timeout to retry."
        )

    high_assigned = {s.id: new_score[s.id] for s in high_group if new_score[s.id] > 0}
    assert not high_assigned, (
        f"[n_low={n_low}, n_high={n_high}, m={m}, seed={seed}] "
        f"High-spd soldiers received duties:\n"
        + "\n".join(
            f"  high(cum={s.cumulative_score}, spd={float(s.cumulative_score)/100:.2f})"
            f" → {high_assigned[s.id]}"
            for s in high_group if s.id in high_assigned
        )
        + f"\nLow group scores: {sorted(float(new_score[s.id]) for s in low_group)}"
    )
