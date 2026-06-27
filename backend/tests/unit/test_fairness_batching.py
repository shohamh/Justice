"""
Cross-batch fairness for soldiers with IDENTICAL inputs.

MOTIVATION
----------
test_fairness.py's `test_convergence_equal_spd_shares_evenly` shows the
fairness objective splits duties evenly among identical soldiers — but only
within a SINGLE build_model() call. Production runs decompose into many
sequential batches (app.algorithm.solver.solve, "interleaved" decomposition),
each a SEPARATE CP-SAT solve that only sees the running totals carried
forward from prior batches.

The L1 objective (Σ|total_i - mu_const|) is piecewise-linear: as long as two
soldiers' running totals stay on the same side of the per-batch mean, every
split of new duties between them scores IDENTICALLY (the sum only depends on
the total handed out, not who gets it). The only thing that can break such a
tie is the secondary `count_spread` term — but that term resets every batch
and only measures THIS batch's new counts, never the cumulative gap. So an
unequal split can tip the balance toward one identical soldier over another
with no mechanism to correct it in a later batch, even when a perfectly even
split is achievable (verified below with a duty count where the tied group's
total *is* evenly divisible, ruling out "unavoidable remainder" as the cause).

THE FIX: a lexicographic second stage (SolverSettings.tiebreak_mode="range"),
applied in app.algorithm.solver._solve_with_settings:
  1. Solve with today's L1 objective unchanged (stage 1).
  2. Pin Σdev_terms <= its just-proven value, hint with stage 1's assignment,
     and re-solve with a NEW dominant tier inserted above the existing
     prior/count-spread/reserve-proximity tiers (app.algorithm.model.
     apply_tiebreak_objective): minimise max(total_i) - min(total_i) over all
     eligible soldiers. O(n), cheap — reuses AddMaxEquality/AddMinEquality
     like the pre-existing count_spread tier. A full pairwise variant
     (Σ_i<j |total_i - total_j|, O(n^2) but still linear) was also tried and
     measured: it never found ANY improvement within any tested time budget
     (up to 60s/batch) at n=100 soldiers, so it was dropped — "range" is
     blind to ties that aren't the population's global extremes, but
     resolves the production-representative case and is the only one of the
     two that's actually affordable at realistic batch sizes.
  3. If stage 2 doesn't finish within its own (shorter) time budget, fall
     back to stage 1's untouched, already-valid result — never worse than
     today's "off" behaviour.

The new tier sits ABOVE reserve proximity but DELIBERATELY DROPS prior_term
and count_spread rather than carrying them forward: both are weaker, already
-superseded proxies for the thing range now measures directly (count_offset
can be compressed to near-meaningless precision by auto-range scaling, and
count_spread only ever measured *this batch's* new counts — the exact
mechanism that caused the original bug). Reserve proximity is kept because
it's not a load-balancing proxy at all — it's an orthogonal placement-quality
preference unrelated to the spread bug this mechanism exists to fix (see
test_tiebreak_prefers_reserve_proximity_among_range_ties below).
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta
from types import SimpleNamespace
from decimal import Decimal

import pytest
from ortools.sat.python.cp_model import CpModel, CpSolver

from app.algorithm.model import FairnessTerms, apply_tiebreak_objective
from app.algorithm.solver import solve
from app.algorithm.types import DutyBlock, SoldierInput, SolverSettings


def _soldier(effort_per_milli: int) -> SoldierInput:
    return SoldierInput(
        id=uuid.uuid4(),
        enrolled_at=date(2025, 1, 1),
        cumulative_score=Decimal("0"),
        active_days=200,
        effort_offset=0,
        effort_per_milli=effort_per_milli,
    )


def _duty(start: date, duty_type_id: uuid.UUID) -> DutyBlock:
    return DutyBlock(
        id=uuid.uuid4(),
        duty_type_id=duty_type_id,
        duty_location_id=uuid.uuid4(),
        start_date=start,
        end_date=start,
        score_per_day=Decimal("1.0"),
    )


def _run(tiebreak_mode: str) -> list[int]:
    """4 IDENTICAL soldiers compete for 72 same-type duties over several
    interleaved batches, alongside 2 "heavy" soldiers with a moderately
    higher effort_per_milli (4x) that pulls the per-batch mean up enough to
    keep the tied group in L1's flat/indifferent zone for the whole run
    (mirroring the production scenario: soldiers sharing one duty type while
    a separate, costlier group dominates the population mean).

    72 duties is calibrated so that, at this seed, the tied group's total
    (64, after the heavy pair absorbs 8) IS evenly divisible by 4 — so a
    perfect [16,16,16,16] split is achievable and "off" still misses it,
    ruling out an unavoidable remainder as the explanation.

    Density caps (T/R) are set generously wide so they never bind — this
    isolates the fairness objective itself as the only mechanism in play.
    Returns the tied group's sorted duty counts."""
    duty_type = uuid.uuid4()
    tied = [_soldier(1000) for _ in range(4)]
    heavy = [_soldier(4000) for _ in range(2)]
    duties = [_duty(date(2027, 1, 1) + timedelta(days=i), duty_type) for i in range(72)]

    settings = SolverSettings(
        T=200, Wt=200, R=200, Wr=200, alpha=Decimal("1.0"),
        decomposition="interleaved", batching_enabled=True,
        interleaved_batch_size=6, batch_time_limit_seconds=10,
        seed=1, tiebreak_mode=tiebreak_mode, tiebreak_time_limit_seconds=10,
    )

    result = solve(tied + heavy, duties, [], settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")

    counts = Counter(a.soldier_id for a in result.assignments)
    return sorted(counts.get(s.id, 0) for s in tied)


def test_off_mode_achieves_even_split_via_swap_pass():
    """The post-solve swap pass recovers the achievable [16, 16, 16, 16] split
    even when tiebreak_mode='off', by greedily moving duties from over-loaded
    soldiers to under-loaded ones after the CP-SAT solve completes."""
    tied_counts = _run("off")
    assert max(tied_counts) - min(tied_counts) == 0, (
        f"4 identical soldiers should split an evenly-divisible total "
        f"perfectly evenly after the swap pass; got {tied_counts}"
    )


def test_range_tiebreak_splits_identical_soldiers_evenly():
    """tiebreak_mode='range' recovers the achievable [16, 16, 16, 16] split
    that 'off' misses, by pinning stage 1's proven L1 value and re-solving
    with a purely linear tie-break objective among the solutions L1 can't
    distinguish (see apply_tiebreak_objective)."""
    tied_counts = _run("range")
    assert tied_counts == [16, 16, 16, 16], (
        f"tiebreak_mode='range' should recover the perfectly even split; "
        f"got {tied_counts}"
    )


def test_tiebreak_does_not_protect_prior_ordering_among_range_ties():
    """apply_tiebreak_objective intentionally does NOT carry prior_term or
    count_spread into stage 2 — both are weaker, already-superseded proxies
    for the thing range now measures directly (see the design discussion: a
    soldier's count_offset can be compressed to near-meaningless precision by
    auto-range scaling, and count_spread only ever measured *this batch's*
    new counts, which is the exact mechanism that caused the original bug).

    Hand-engineered tie: soldier A (count_offset=0) and soldier B
    (count_offset=2000) split 3 duties of weight 1000. Splits (countA=2,
    countB=1) and (countA=3, countB=0) both achieve the SAME minimal spread
    (1000), so range alone can't distinguish them. If prior_term were still
    in the objective (the old behaviour), forcing the prior-violating
    (countA=2, countB=1) split via a constraint would make the model strictly
    WORSE — prior_term would be nonzero where the unconstrained optimum has
    it at zero. With prior_term gone, forcing that split should reach the
    SAME optimal objective value as the unconstrained solve, since both
    splits are genuinely tied on the only term left (spread)."""
    def _build():
        model = CpModel()
        x_a = [model.NewBoolVar(f"a{i}") for i in range(3)]
        x_b = [model.NewBoolVar(f"b{i}") for i in range(3)]
        for i in range(3):
            model.Add(x_a[i] + x_b[i] == 1)
        count_a, count_b = sum(x_a), sum(x_b)
        offset_a, offset_b, weight = 0, 2000, 1000
        total_a = offset_a + weight * count_a
        total_b = offset_b + weight * count_b
        terms = FairnessTerms(
            eligible_total_exprs=[total_a, total_b],
            eligible_offsets=[offset_a, offset_b],
            total_new_weight=3 * weight,
            prior_terms=[offset_a * count_a, offset_b * count_b],
            count_vars=[count_a, count_b],
            total_ub=10_000,
            dev_terms=[],
        )
        apply_tiebreak_objective(
            model, {}, [None] * 3, SolverSettings(), None, terms, achieved_l1=0,
        )
        return model, count_a, count_b

    unconstrained_model, count_a, count_b = _build()
    solver = CpSolver()
    status = solver.Solve(unconstrained_model)
    assert solver.StatusName(status) == "OPTIMAL"
    best_objective = solver.ObjectiveValue()

    forced_model, forced_count_a, forced_count_b = _build()
    forced_model.Add(forced_count_a == 2)  # force the prior-violating split
    forced_solver = CpSolver()
    forced_status = forced_solver.Solve(forced_model)
    assert forced_solver.StatusName(forced_status) == "OPTIMAL"

    assert forced_solver.ObjectiveValue() == best_objective, (
        f"forcing the prior-violating (2, 1) split should reach the same "
        f"optimal objective value as the unconstrained solve "
        f"({best_objective}) now that prior_term is no longer in the "
        f"objective; got {forced_solver.ObjectiveValue()}"
    )


def test_tiebreak_prefers_reserve_proximity_among_range_ties():
    """reserve proximity DOES remain a protected tier below range — unlike
    prior/count_spread, it's not a load-balancing proxy that range
    supersedes; it's an orthogonal placement-quality preference (assign
    reserve duties to hierarchically-close soldiers) that has nothing to do
    with the spread bug this whole mechanism exists to fix.

    Hand-engineered tie: 2 IDENTICAL soldiers (same offset, same weight) and
    2 duties, one of them is_reserve=True. The unique spread-minimising
    split is 1 duty each (any 2-0 split is far worse) — but which specific
    soldier gets the reserve duty vs the normal one is still free. Soldier A
    is hierarchically close to the reserve duty (dist=1), soldier B is far
    (dist=10): the model should assign the reserve duty to A."""
    model = CpModel()
    reserve_duty = SimpleNamespace(is_reserve=True)
    normal_duty = SimpleNamespace(is_reserve=False)
    duty_list = [reserve_duty, normal_duty]

    x_a_reserve = model.NewBoolVar("a_reserve")
    x_b_reserve = model.NewBoolVar("b_reserve")
    x_a_normal = model.NewBoolVar("a_normal")
    x_b_normal = model.NewBoolVar("b_normal")
    model.Add(x_a_reserve + x_b_reserve == 1)
    model.Add(x_a_normal + x_b_normal == 1)
    x = {
        (0, 0): x_a_reserve, (0, 1): x_b_reserve,
        (1, 0): x_a_normal, (1, 1): x_b_normal,
    }

    weight = 1000
    count_a = x_a_reserve + x_a_normal
    count_b = x_b_reserve + x_b_normal
    total_a = weight * count_a
    total_b = weight * count_b

    terms = FairnessTerms(
        eligible_total_exprs=[total_a, total_b],
        eligible_offsets=[0, 0],
        total_new_weight=2 * weight,
        prior_terms=[],
        count_vars=[count_a, count_b],
        total_ub=10_000,
        dev_terms=[],
    )
    settings = SolverSettings(reserve_hierarchy_weight=Decimal("0.5"))
    reserve_dist = {(0, 0): 1, (0, 1): 10}  # soldier 0 (A) close, soldier 1 (B) far
    apply_tiebreak_objective(model, x, duty_list, settings, reserve_dist, terms, achieved_l1=0)
    solver = CpSolver()
    status = solver.Solve(model)

    assert solver.StatusName(status) == "OPTIMAL"
    assert solver.Value(x_a_reserve) == 1, (
        "among spread-tied splits, the reserve duty should go to the "
        "hierarchically-closer soldier (A), not B"
    )
