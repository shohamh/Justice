"""
Fairness tests for the CP-SAT assignment model.

FAIRNESS DEFINITION
===================

"Fair" means every eligible soldier converges toward the same duty burden
relative to their time in service.  The metric is:

    score_per_day (spd) = cumulative_score / active_days

where:
  - cumulative_score   total duty points earned across all runs
  - active_days        days since enlistment, minus fully-exempt days

A perfectly fair unit has spd(A) == spd(B) for every pair A, B.

The algorithm enforces three fairness properties per run:

PROPERTY 1 — CONVERGENCE
    A soldier with a lower historical spd should receive MORE duties in a
    single run than a soldier with a higher spd.  The goal is to close the
    gap between them, not to distribute duties evenly by count.

    Example: A (spd=0) and B (spd=0.5) competing for 2 duties.
    Fair: A gets both duties (counts: A=2, B=0).
    Unfair: each gets one (counts: A=1, B=1) — this widens the relative gap.

    Note: evenness of *count* is NOT the right property.  Equal counts are
    fair only when both soldiers start at the same spd.

    Implemented via cumulative norm:
        norm_s = (cumulative_score * 1000 + new_score * 1000) / active_days
    Primary objective: Minimize max(norm_s) across all soldiers.
    Secondary objective: Maximize min(norm_s) among eligible soldiers.

PROPERTY 2 — PRIORITY (score_per_day-aware)
    When forced to choose between soldiers, the one with the lower
    historical spd is assigned first.

    Crucially, raw cumulative_score is NOT the right signal: a soldier
    with 10 pts over 200 days (spd = 0.05) is *less* loaded than one
    with 10 pts over 100 days (spd = 0.10) and should receive duties
    first, even though both have the same cumulative score.

    Implemented as the secondary (tiebreaker) penalty:
        penalty(assignment to s) ∝  s.cumulative_score * 1000 // s.active_days

PROPERTY 3 — NON-CONCENTRATION
    A soldier who is already heavily loaded (high spd) receives no new
    assignments as long as lighter-loaded eligible soldiers exist.

    Emerges from Properties 1 + 2 together: the cumulative objective
    penalises assigning to soldiers who are already at a high norm,
    and the tiebreaker further pushes assignments toward lower-spd soldiers.

NOTE: Property 2 is tested explicitly because it was the original bug —
raw cumulative was used as the tiebreaker, which treated two soldiers
with the same score but different active_days identically.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

import pytest
from ortools.sat.python.cp_model import CpSolver

from app.algorithm.model import build_model
from app.algorithm.types import DutyBlock, SoldierInput, SolverSettings


# ─── helpers ─────────────────────────────────────────────────────────────────

def _soldier(score: float, active_days: int = 100) -> SoldierInput:
    from app.services.effort_score import EFFORT_SCALE
    # The model optimises quarterly EFFORT. Map this score-based scenario onto
    # effort: historical load = score_per_day × EFFORT_SCALE, with a uniform
    # marginal so a new 1-day duty of score s raises effort by s/active_days ×
    # EFFORT_SCALE (i.e. score_per_day's marginal). effort_per_milli must be set
    # — with it at 0 the assignment can't move effort and the choice is arbitrary.
    spd = score / active_days if active_days > 0 else 0
    effort_offset = int(spd * EFFORT_SCALE)
    return SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2025, 1, 1),
        cumulative_score=Decimal(str(score)),
        active_days=active_days,
        effort_offset=effort_offset,
        effort_per_milli=EFFORT_SCALE // (active_days * 1000),
    )


def _duty(start: date, score: float = 1.0) -> DutyBlock:
    """Single-day duty."""
    return DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=uuid.uuid4(),
        duty_location_id=uuid.uuid4(),
        start_date=start,
        end_date=start,
        score_per_day=Decimal(str(score)),
    )


def _duties(n: int, *, start: date, gap_weeks: int = 2) -> list[DutyBlock]:
    """n non-overlapping single-day duties separated by gap_weeks weeks."""
    return [_duty(start + timedelta(weeks=i * gap_weeks)) for i in range(n)]


def _solve(soldiers, duties, **kw) -> dict[uuid.UUID, uuid.UUID]:
    """Solve and return {duty_id: soldier_id}. Asserts feasibility."""
    settings = SolverSettings(**kw)
    model, x = build_model(soldiers, duties, [], settings)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = 15
    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    assert status_name in ("OPTIMAL", "FEASIBLE"), f"Solver returned {status_name}"
    return {
        duties[di].id: soldiers[si].id
        for (di, si), var in x.items()
        if solver.Value(var)
    }


def _counts(assigned: dict, soldiers: list[SoldierInput]) -> dict[uuid.UUID, int]:
    """Duties assigned per soldier (0 for unassigned soldiers)."""
    c = Counter(assigned.values())
    return {s.id: c.get(s.id, 0) for s in soldiers}


def _new_spd(assigned: dict, soldiers: list[SoldierInput],
             duties: list[DutyBlock]) -> dict[uuid.UUID, float]:
    """Incremental score_per_day added in this run for each soldier."""
    duty_score = {d.id: float(d.score_per_day) for d in duties}
    new_score: dict[uuid.UUID, float] = {s.id: 0.0 for s in soldiers}
    for duty_id, soldier_id in assigned.items():
        new_score[soldier_id] += duty_score[duty_id]
    return {s.id: new_score[s.id] / s.active_days for s in soldiers}


STD = dict(T=7, W=14, alpha=Decimal("1.0"))

# ─── Property 1: Convergence ──────────────────────────────────────────────────


def test_convergence_lower_spd_gets_more_duties():
    """2 soldiers: A (spd=0) vs B (spd=0.5), 2 non-overlapping duties.

    Fairness means closing the gap, NOT equal counts.  The correct outcome is
    A gets both duties (post-run spd: A≈0.02, B=0.50), not A=1 B=1 (which
    would give A=0.01 and B=0.51 — barely narrowing the gap).

    This is the core convergence property: low-spd soldiers absorb new duties
    aggressively while high-spd soldiers are left idle."""
    low  = _soldier(score=0.0,  active_days=100)   # spd = 0.00
    high = _soldier(score=50.0, active_days=100)   # spd = 0.50
    duties = _duties(2, start=date(2027, 1, 1))

    assigned = _solve([low, high], duties, **STD)
    counts = _counts(assigned, [low, high])

    assert counts[low.id] == 2, (
        f"Low-spd soldier (spd=0) should get both duties when competing with "
        f"high-spd (spd=0.5); got low={counts[low.id]}, high={counts[high.id]}"
    )
    assert counts[high.id] == 0, (
        f"High-spd soldier (spd=0.5) should receive no duties; "
        f"got {counts[high.id]}"
    )


def test_convergence_equal_spd_shares_evenly():
    """When all soldiers start at the same spd, duties are split evenly.

    With A=B=C at spd=0.10 and 6 duties, equal counts (2 each) is the only
    way to keep all post-run norms equal.  This is the degenerate case where
    convergence and evenness coincide."""
    soldiers = [_soldier(score=10.0, active_days=100) for _ in range(3)]
    duties = _duties(6, start=date(2027, 3, 1))

    assigned = _solve(soldiers, duties, **STD)
    counts = list(_counts(assigned, soldiers).values())

    assert all(c == 2 for c in counts), (
        f"Equal-spd soldiers should each get 2 duties (6 / 3); "
        f"got {sorted(counts)}"
    )


def test_convergence_graduated_spd_receives_descending_duties():
    """3 soldiers at ordered spd values (0, 0.1, 0.2) compete for 6 duties.

    The lowest-spd soldier should receive the most duties, the highest the
    fewest.  Strictly: count(low) ≥ count(mid) ≥ count(high)."""
    low  = _soldier(score=0.0,  active_days=100)  # spd = 0.00
    mid  = _soldier(score=10.0, active_days=100)  # spd = 0.10
    high = _soldier(score=20.0, active_days=100)  # spd = 0.20
    duties = _duties(6, start=date(2027, 5, 1))

    assigned = _solve([low, mid, high], duties, **STD)
    counts = _counts(assigned, [low, mid, high])

    assert counts[low.id] >= counts[mid.id] >= counts[high.id], (
        f"Duty counts should be non-increasing with spd; "
        f"got low={counts[low.id]}, mid={counts[mid.id]}, high={counts[high.id]}"
    )


# ─── Property 2: Priority (score_per_day-aware) ───────────────────────────────


def test_priority_lower_cumulative_same_active_days():
    """1 duty, 2 soldiers with the same active_days.
    Lower cumulative score (lower spd) wins."""
    heavy = _soldier(score=20.0, active_days=100)   # spd = 0.20
    light = _soldier(score=5.0,  active_days=100)   # spd = 0.05
    duty = _duty(date(2027, 7, 1))

    assigned = _solve([heavy, light], [duty], **STD)

    assert assigned[duty.id] == light.id, (
        "Soldier with spd=0.05 (5 pts / 100 days) should be preferred over "
        "spd=0.20 (20 pts / 100 days)"
    )


def test_priority_same_cumulative_higher_active_days_wins():
    """1 duty, 2 soldiers with IDENTICAL cumulative scores but different active_days.

    This is the core active-days-awareness test.  Using raw cumulative_score
    as the tiebreaker would treat both soldiers equally; using score_per_day
    correctly identifies the longer-serving soldier as less loaded:

        longer_service: 10 pts / 200 days → spd = 0.050  ← should win
        shorter_service: 10 pts / 100 days → spd = 0.100

    The longer-serving soldier is assigned because:
      - Primary objective: assigning them adds 1000/200 = 5 incremental milli-norm
        vs 1000/100 = 10 for the shorter-serving soldier → primary already prefers them
      - Tiebreaker: hist_milli = 10000//200 = 50 vs 10000//100 = 100 → also prefers them
    """
    longer = _soldier(score=10.0, active_days=200)   # spd = 0.050
    shorter = _soldier(score=10.0, active_days=100)  # spd = 0.100
    duty = _duty(date(2027, 8, 1))

    assigned = _solve([longer, shorter], [duty], **STD)

    assert assigned[duty.id] == longer.id, (
        "Soldier with spd=0.05 (10 pts / 200 days) should be preferred over "
        "spd=0.10 (10 pts / 100 days) — same cumulative, different service length"
    )


def test_priority_three_soldiers_lowest_spd_wins():
    """1 duty, 3 soldiers at strictly ordered spd values.
    The lowest-spd soldier always wins."""
    high = _soldier(score=30.0, active_days=100)  # spd = 0.30
    mid  = _soldier(score=15.0, active_days=100)  # spd = 0.15
    low  = _soldier(score=3.0,  active_days=100)  # spd = 0.03
    duty = _duty(date(2027, 9, 1))

    assigned = _solve([high, mid, low], [duty], **STD)

    assert assigned[duty.id] == low.id, (
        "Lowest-spd soldier (3 pts / 100 days = 0.03) must be assigned "
        "over mid (0.15) and high (0.30)"
    )


def test_priority_spd_not_raw_score():
    """Regression: a high-score soldier with many active days can have a LOWER spd
    than a low-score soldier with few active days.  The one with lower spd wins.

    heavy_but_long: 40 pts / 400 days → spd = 0.10
    light_but_short: 8 pts / 40 days  → spd = 0.20   ← heavier relative burden

    Without active_days normalisation the algorithm would wrongly assign to
    light_but_short (lower raw score = 8 vs 40).  With spd normalisation it
    correctly assigns to heavy_but_long (lower spd = 0.10 vs 0.20)."""
    heavy_but_long  = _soldier(score=40.0, active_days=400)  # spd = 0.10
    light_but_short = _soldier(score=8.0,  active_days=40)   # spd = 0.20
    duty = _duty(date(2027, 10, 1))

    assigned = _solve([heavy_but_long, light_but_short], [duty], **STD)

    assert assigned[duty.id] == heavy_but_long.id, (
        "Soldier with spd=0.10 (40 pts / 400 days) should win over "
        "spd=0.20 (8 pts / 40 days) — lower burden rate despite higher raw score"
    )


# ─── Property 3: Non-concentration ───────────────────────────────────────────


def test_nonconcentration_heavy_soldier_skipped():
    """1 heavy-spd soldier + 3 zero-spd soldiers, 3 duties.

    The heavy soldier must receive 0 new duties.  Every assignment to them
    would raise max_new_norm by the same amount as assigning to a zero-spd
    soldier (same point value), but the tiebreaker penalises the heavy
    soldier more — so they are consistently skipped."""
    heavy = _soldier(score=30.0, active_days=100)   # spd = 0.30
    zeros = [_soldier(score=0.0) for _ in range(3)]
    duties = _duties(3, start=date(2027, 11, 1))

    assigned = _solve([heavy] + zeros, duties, **STD)

    assert heavy.id not in assigned.values(), (
        "Heavy-spd soldier (0.30) should receive no new duties when "
        "zero-spd soldiers are available"
    )


def test_nonconcentration_high_history_does_not_pin_objective():
    """Regression for the 'pinned ceiling' bug.

    Old behaviour: one soldier with high historical score dominated
    max_cum_norm, making the algorithm indifferent to how new assignments
    were distributed among everyone else.  This led to concentration.

    New behaviour: the objective uses max *incremental* norm, which is
    never dominated by historical scores.  Result: equal distribution
    regardless of how unequal the history is.

    Setup: 1 soldier with score=30 + 3 soldiers with score=0, 3 duties.
    The 3 new duties should go one-each to the zero-score soldiers."""
    high_history = _soldier(score=30.0, active_days=100)
    zeros = [_soldier(score=0.0) for _ in range(3)]
    duties = _duties(3, start=date(2027, 12, 1))

    assigned = _solve([high_history] + zeros, duties, **STD)
    counts = _counts(assigned, zeros)

    assert all(c == 1 for c in counts.values()), (
        f"Each zero-score soldier should get exactly 1 duty; "
        f"got {sorted(counts.values())} (high-history got "
        f"{sum(1 for v in assigned.values() if v == high_history.id)})"
    )


def test_nonconcentration_max_assignments_bounded():
    """5 equal soldiers, 10 duties → every soldier gets exactly 2.

    If the algorithm concentrated assignments on fewer soldiers
    (e.g., [4, 4, 2, 0, 0]) the max incremental spd would be 4/100 = 0.04,
    vs 2/100 = 0.02 for the even split.  The objective forces the minimum."""
    soldiers = [_soldier(0.0) for _ in range(5)]
    duties = _duties(10, start=date(2028, 1, 1))

    assigned = _solve(soldiers, duties, **STD)
    counts = list(_counts(assigned, soldiers).values())

    assert max(counts) == 2, (
        f"No soldier should get more than 2 duties (10 / 5 = 2); "
        f"got {sorted(counts)}"
    )
    assert min(counts) == 2, (
        f"No soldier should get fewer than 2 duties; got {sorted(counts)}"
    )
