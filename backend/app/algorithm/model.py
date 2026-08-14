from __future__ import annotations

import bisect
import dataclasses
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, overload

from ortools.sat.python.cp_model import CpModel, IntVar, LinearExpr

from app.algorithm.duration import combine_date_time, score_days
from app.algorithm.rest import last_duty_day, rest_violated
from app.algorithm.types import (
    EFFORT_SCALE,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
    node_in_scope,
)


def _block_score(d: DutyBlock) -> int:
    """Total score for completing the entire block, in milli-units (x1000 for integer math)."""
    days = score_days(d.start_date, d.end_date, d.start_time, d.end_time)
    return int(d.score_per_day * Decimal(days) * 1000)


def _duty_dates(d: DutyBlock) -> list[date]:
    dt = d.start_date
    result: list[date] = []
    while dt < d.end_date:
        result.append(dt)
        dt += timedelta(days=1)
    return result


def _existing_dates_by_soldier(
    existing: Sequence[ExistingAssignment], soldier_id: uuid.UUID
) -> set[date]:
    result: set[date] = set()
    for ea in existing:
        if ea.soldier_id == soldier_id:
            dt = ea.start_date
            while dt < ea.end_date:
                result.add(dt)
                dt += timedelta(days=1)
    return result


@dataclass
class FairnessTerms:
    """Count-space inputs to the fairness objective, computed in ``build_model``.

    Carried so the soft-coverage lexicographic solve can re-apply the fairness
    objective after its stage-1 coverage maximization replaces it, without
    rebuilding (and duplicating) the count-space decision variables.
    """

    eligible_total_exprs: list = field(default_factory=list)
    eligible_offsets: list[int] = field(default_factory=list)
    total_new_weight: int = 0
    prior_terms: list = field(default_factory=list)
    count_vars: list[IntVar] = field(default_factory=list)
    total_ub: int = 0
    # Per-soldier |total_i - mu_const| variables from the L1 objective, exposed
    # so a caller can pin Σdev_terms to its already-proven-optimal value and
    # re-solve with a different (tie-break) objective — see
    # apply_tiebreak_objective.
    dev_terms: list[IntVar] = field(default_factory=list)


def build_fairness_objective(
    model: CpModel,
    x: dict[tuple[int, int], IntVar],
    duty_list: Sequence[DutyBlock],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None,
    terms: FairnessTerms,
) -> None:
    """Apply the L1 fairness objective (+ reserve proximity) to ``model``.

    Extracted from ``build_model`` so both the hard-coverage path and the
    soft-coverage lexicographic solve share one objective definition. All the
    count-space pieces it needs (deviation inputs, prior/spread terms) are
    passed in precomputed via ``terms`` so the resulting model is byte-identical
    to the pre-extraction inline version.
    """
    eligible_total_exprs = terms.eligible_total_exprs
    eligible_offsets = terms.eligible_offsets
    total_new_weight = terms.total_new_weight
    prior_terms = terms.prior_terms
    count_vars = terms.count_vars
    total_ub = terms.total_ub
    # Soft objective: hierarchy proximity for reserve blocks
    reserve_dist_terms: list = []
    if reserve_dist is not None:
        gamma_int = int(settings.reserve_hierarchy_weight * 1000)
        for (di, si), var in x.items():
            if duty_list[di].is_reserve:
                dist = reserve_dist.get((di, si), 10)
                reserve_dist_terms.append(gamma_int * dist * var)

    # ── Fairness objective: L1 dispersion of count-space effort ───────────────
    #
    # minimise   Σ_i | total_i − μ |   +   ε · reserve_proximity
    #
    # where total_i = count_offset_i + Σ assigned weight_i(duty), and μ is FIXED
    # to the post-run mean (a constant) so the deviation vars decouple → fast.
    # Because every soldier contributes their own |deviation| term, L1 equalises
    # the WHOLE distribution — including interior sub-populations (e.g. officers
    # clustered at low effort) that a min(max−min) spread is blind to.  This is
    # only tractable because the caller (solver.py) decomposes each run into
    # connected components and chronological batches, so each build_model is small.
    #
    # SECONDARY (below L1) — prefer low-prior soldiers, then split counts evenly.
    # RESERVE PROXIMITY (gamma_int) is the smallest tier.
    # Tiers: L1 ≫ prior ≫ count-spread ≫ reserve proximity.
    # ────────────────────────────────────────────────────────────────────────

    alpha_int = int(settings.alpha * 1000)
    dist_term = sum(reserve_dist_terms) if reserve_dist_terms else 0

    if eligible_total_exprs and alpha_int > 0:
        # Tiers (each ≫ the next): L1 ≫ prior ≫ count-spread ≫ reserve proximity.
        l1_w = 100_000_000_000  # 1e11
        prior_w = 1_000_000     # 1e6
        # 1e5 — empirically the minimum that reliably breaks L1-tied ties toward
        # an even count split instead of CP-SAT settling on a lopsided
        # near-tied allocation (verified: 1e4 leaves some soldiers at 0 while
        # others double up even given 3x the normal time budget with no stall
        # cutoff; 1e5 finds the genuinely even split). Still ≪ prior_w.
        count_w = 100_000        # 1e5 — above the per-move reserve-distance term
        n_elig = len(eligible_total_exprs)
        mu_const = (sum(eligible_offsets) + total_new_weight) // n_elig

        dev_terms: list[IntVar] = []
        for i, total in enumerate(eligible_total_exprs):
            dev = model.NewIntVar(0, total_ub, f"effort_dev{i}")
            model.Add(dev >= total - mu_const)
            model.Add(dev >= mu_const - total)
            dev_terms.append(dev)
        l1_term = sum(dev_terms)
        terms.dev_terms = dev_terms

        prior_term = sum(prior_terms) if prior_terms else 0

        count_spread: LinearExpr | int = 0
        if len(count_vars) > 1:
            max_count_var = model.NewIntVar(0, len(duty_list), "max_count")
            min_count_var = model.NewIntVar(0, len(duty_list), "min_count")
            model.AddMaxEquality(max_count_var, count_vars)
            model.AddMinEquality(min_count_var, count_vars)
            count_spread = max_count_var - min_count_var

        model.Maximize(
            -l1_w * l1_term - prior_w * prior_term - count_w * count_spread - dist_term
        )
    else:
        model.Minimize(dist_term if reserve_dist_terms else 0)


def apply_tiebreak_objective(
    model: CpModel,
    x: dict[tuple[int, int], IntVar],
    duty_list: Sequence[DutyBlock],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None,
    terms: FairnessTerms,
    achieved_l1: int,
) -> None:
    """Lexicographic second stage: pin L1 dispersion to its proven-optimal
    value, then insert a new dominant tier — above reserve proximity, but
    DELIBERATELY NOT above prior/count-spread.

    The L1 objective (``Σ|total_i - mu_const|``) is piecewise-linear: any
    split of new duties between two soldiers who stay on the same side of
    ``mu_const`` scores identically, so it cannot prefer an even split over a
    lopsided one between otherwise-identical soldiers (see
    test_fairness_batching.py). Pinning ``Σdev_terms <= achieved_l1`` keeps
    every solution this stage considers exactly as good on L1 as the one
    already found, while letting a new tie-break tier — ``max(total_i) -
    min(total_i)`` over all eligible soldiers — choose among the (possibly
    many) solutions tied on L1. This is cheap: O(n), reusing
    AddMaxEquality/AddMinEquality exactly like the existing count_spread tier.
    It can still be blind to ties that aren't the population's global
    extremes (e.g. a structurally different soldier group already occupies
    the max/min), but empirically resolves the production-representative
    case (see backend git history on this branch for the n=80-100 benchmarks
    that ruled out a full pairwise tier — O(n^2) and never finished within
    any tested time budget at that scale).

    prior_term and count_spread are NOT carried into this stage (unlike
    reserve proximity, which is): both were already L1's own tie-breakers
    for exactly the region this stage now handles, and both are weaker
    proxies for the same goal range now measures directly — prior_term via
    count_offset, which auto-range scaling can compress to near-meaningless
    precision (see this branch's design discussion), and count_spread via
    *this batch's new counts only*, which is the exact blind spot that
    caused the original bug. Once range exists, neither adds a signal worth
    protecting at the cost of (a) more model complexity and (b) potentially
    overriding the more direct, cumulative range result for a coarser proxy.
    Reserve proximity is kept because it isn't a load-balancing proxy at
    all — it's an orthogonal placement-quality preference (assign reserve
    duties to hierarchically-close soldiers).
    """
    if terms.dev_terms:
        model.Add(sum(terms.dev_terms) <= achieved_l1)

    eligible = terms.eligible_total_exprs
    reserve_dist_terms: list = []
    if reserve_dist is not None:
        gamma_int = int(settings.reserve_hierarchy_weight * 1000)
        for (di, si), var in x.items():
            if duty_list[di].is_reserve:
                dist = reserve_dist.get((di, si), 10)
                reserve_dist_terms.append(gamma_int * dist * var)
    dist_term = sum(reserve_dist_terms) if reserve_dist_terms else 0

    if len(eligible) <= 1:
        model.Minimize(dist_term if reserve_dist_terms else 0)
        return

    # spread_w just needs to dominate dist_term (bounded by gamma_int * max
    # hierarchy distance per reserve duty — small relative to total_ub),
    # nowhere near as large a gap as l1_w/prior_w needed since there's no
    # other tier left to protect against here.
    spread_w = 1_000_000_000  # 1e9

    ub = terms.total_ub
    max_v = model.NewIntVar(0, ub, "tb_max_total")
    min_v = model.NewIntVar(0, ub, "tb_min_total")
    model.AddMaxEquality(max_v, eligible)
    model.AddMinEquality(min_v, eligible)
    spread_term = max_v - min_v

    model.Maximize(-spread_w * spread_term - dist_term)


@overload
def build_model(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = ...,
    coverage: Literal["hard", "soft"] = ...,
    with_obj_terms: Literal[False] = ...,
) -> tuple[CpModel, dict[tuple[int, int], IntVar]]: ...


@overload
def build_model(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = ...,
    coverage: Literal["hard", "soft"] = ...,
    with_obj_terms: Literal[True] = ...,
) -> tuple[CpModel, dict[tuple[int, int], IntVar], FairnessTerms]: ...


def build_model(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    coverage: Literal["hard", "soft"] = "hard",
    with_obj_terms: bool = False,
) -> (
    tuple[CpModel, dict[tuple[int, int], IntVar]]
    | tuple[CpModel, dict[tuple[int, int], IntVar], FairnessTerms]
):
    model = CpModel()
    duty_list = list(duties)
    soldier_list = list(soldiers)
    Wt = settings.Wt
    Wr = settings.Wr
    T = settings.T
    R = settings.R

    # Build lookup maps
    exempt_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for s in soldier_list:
        exempt_map[s.id] = s.exempted_duty_type_ids

    location_exempt_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for s in soldier_list:
        location_exempt_map[s.id] = s.exempted_duty_location_ids

    constraint_map: dict[uuid.UUID, set[date]] = {}
    for s in soldier_list:
        dates: set[date] = set()
        for cs, ce in s.approved_constraint_dates:
            dt = cs
            while dt <= ce:
                dates.add(dt)
                dt += timedelta(days=1)
        constraint_map[s.id] = dates

    # Pre-build duty date sets once so the eligible-filter and no-overlap loops
    # don't re-expand the same date range O(S) and O(S×W) times respectively.
    duty_dates_cache: dict[int, frozenset[date]] = {
        di: frozenset(_duty_dates(d)) for di, d in enumerate(duty_list)
    }

    # Pre-build existing-assignment date sets per soldier (all and real-only) once
    # so the no-overlap and rolling-window loops don't re-scan existing O(S) times.
    _existing_real = [e for e in existing if not e.is_reserve]
    existing_dates_cache: dict[uuid.UUID, set[date]] = {
        s.id: _existing_dates_by_soldier(existing, s.id) for s in soldier_list
    }
    existing_real_dates_cache: dict[uuid.UUID, set[date]] = {
        s.id: _existing_dates_by_soldier(_existing_real, s.id) for s in soldier_list
    }

    # Pre-filter eligible (duty, soldier) pairs
    eligible: list[tuple[int, int]] = []
    soldier_duties: dict[int, list[int]] = defaultdict(list)
    for di, d in enumerate(duty_list):
        for si, s in enumerate(soldier_list):
            if d.duty_type_id in exempt_map.get(s.id, set()):
                continue
            if d.duty_location_id in location_exempt_map.get(s.id, set()):
                continue
            constrained_dates = constraint_map.get(s.id, set())
            if duty_dates_cache[di] & constrained_dates:
                continue
            if not node_in_scope(d.eligible_node_ids, s.path_ids):
                continue
            if settings.enforce_weapon_qualification and d.id in s.weapon_ineligible_duty_block_ids:
                continue
            if d.id in s.future_ineligible_duty_block_ids:
                continue
            eligible.append((di, si))
            soldier_duties[si].append(di)

    # Decision variables: x[di, si] = 1 if soldier si gets duty di
    x: dict[tuple[int, int], IntVar] = {}
    for di, si in eligible:
        x[(di, si)] = model.NewBoolVar(f"x_d{di}_s{si}")

    # Coverage constraint. Hard: every duty assigned to exactly one soldier.
    # Soft: each duty assigned to at most one soldier (unplaceable duties left
    # unselected so the caller can defer them).
    # In both modes we skip duties with zero eligible soldiers rather than
    # adding sum([]) == 1 (which would be 0 == 1 — globally infeasible) or
    # sum([]) <= 1 (trivially true, harmless but wasteful). Duties with no
    # eligible soldier are simply left uncovered; the caller's coverage check
    # detects and reports the shortfall.
    for di in range(len(duty_list)):
        vars_for_d = [x[(di, si)] for (dii, si) in eligible if dii == di]
        if not vars_for_d:
            continue
        if coverage == "soft":
            model.Add(sum(vars_for_d) <= 1)
        else:
            model.Add(sum(vars_for_d) == 1)

    # ── Sub-unit node quotas ────────────────────────────────────────────────
    # For each duty with node_quotas, force the exact count of assigned
    # soldiers whose path_ids contains that node (itself or any descendant).
    # Slots not covered by any quota remain governed only by the coverage
    # constraint above (any eligible soldier).
    for di, d in enumerate(duty_list):
        if not d.node_quotas:
            continue

        # Under soft coverage, a quota'd duty must still be left feasible to
        # leave entirely unfilled (the soft escape valve). Reify "this duty
        # is covered" as a bool and only enforce quotas when it's set; the
        # reification is equivalent to the bare `sum(vars_for_d) <= 1` above
        # since the sum is 0 or 1 either way. Hard coverage already forces
        # sum(vars_for_d) == 1, so the quota always applies unconditionally.
        covered: IntVar | None = None
        if coverage == "soft":
            vars_for_d = [x[(di, si)] for (dii, si) in eligible if dii == di]
            if vars_for_d:
                covered = model.NewBoolVar(f"covered_d{di}")
                model.Add(sum(vars_for_d) == covered)

        for node_id, count in d.node_quotas.items():
            matching_vars = [
                x[(di, si)] for (dii, si) in eligible
                if dii == di and node_id in soldier_list[si].path_ids
            ]
            if not matching_vars:
                continue
            constraint = model.Add(sum(matching_vars) == count)
            if covered is not None:
                constraint.OnlyEnforceIf(covered)

    # Hard constraint 2: No overlap — a soldier cannot be assigned two duties covering the same day
    all_dates_set: set[date] = set()
    for di in range(len(duty_list)):
        all_dates_set.update(duty_dates_cache[di])

    for si, s in enumerate(soldier_list):
        existing_dates = existing_dates_cache[s.id]
        for t in sorted(all_dates_set):
            day_vars = [x[(di, si)] for di in soldier_duties.get(si, [])
                        if t in duty_dates_cache[di]]
            if not day_vars:
                continue
            if t in existing_dates:
                model.Add(sum(day_vars) == 0)
            else:
                model.Add(sum(day_vars) <= 1)

    # Hard constraint 2b: Rest time — a soldier needs each duty's `rest_hours`
    # of rest between that duty's effective end and the start of their next
    # duty (existing or newly assigned in this same run).
    for si, s in enumerate(soldier_list):
        si_duties = soldier_duties.get(si, [])
        if not si_duties:
            continue

        # Existing (published) assignments block candidates outright — they
        # are fixed, not decision variables.
        for ea in existing:
            if ea.soldier_id != s.id or ea.rest_effective_end_date is None:
                continue
            prior_end_dt = combine_date_time(ea.rest_effective_end_date, ea.rest_effective_end_time)
            for di in si_duties:
                d = duty_list[di]
                if rest_violated(prior_end_dt, d.start_date, d.start_time, ea.rest_hours):
                    model.Add(x[(di, si)] == 0)

        # Candidate-vs-candidate: at most one of a pair too close together can
        # be chosen for this soldier. Bounded lookahead (based on rest_hours)
        # keeps this from becoming an O(n^2) scan over unrelated duties.
        sorted_duties = sorted(si_duties, key=lambda di: duty_list[di].start_date)
        for a_pos, di_a in enumerate(sorted_duties):
            d_a = duty_list[di_a]
            if d_a.rest_hours <= 0:
                continue
            end_day_a = last_duty_day(d_a.start_date, d_a.end_date)
            prior_end_dt = combine_date_time(end_day_a, d_a.end_time)
            lookahead_days = -(-d_a.rest_hours // 24) + 1  # ceil(rest_hours/24) + 1 buffer day
            for di_b in sorted_duties[a_pos + 1:]:
                d_b = duty_list[di_b]
                if d_b.start_date > end_day_a + timedelta(days=lookahead_days):
                    break
                if rest_violated(prior_end_dt, d_b.start_date, d_b.start_time, d_a.rest_hours):
                    model.Add(x[(di_a, si)] + x[(di_b, si)] <= 1)

    # ── Count-space effort ────────────────────────────────────────────────────
    #
    # We optimise quarterly EFFORT (the metric shown on the transparency page and
    # in app/algorithm/explain.py), but expressed as small integers so the L1
    # objective below stays tractable.
    #
    # Auto-range mode (effort_range_max > effort_range_min):
    #   Maps [range_min, range_max] → [0, resolution] so every tick corresponds to
    #   actual spread rather than wasting ticks on the unused [0, 100%] axis.
    #   count_offset_i = clamp((effort_offset_i − range_min) × K / range_size, 0, K)
    #   weight_i(duty) = max(1, effort_per_milli_i × block_score(duty) × K / range_size)
    #   total_ub       = 2K + |duties| + 1   (offset ≤ K, Σweights ≤ K by construction)
    #
    # Fallback (range_size == 0): auto-derive from soldier_list (covers tests that
    # bypass the bridge; the bridge always pre-computes and stamps the range).
    resolution = settings.effort_resolution
    range_size = settings.effort_range_max - settings.effort_range_min
    if range_size <= 0:
        # Derive from the soldiers visible in this model call.
        _active = [s for s in soldier_list if s.effort_per_milli > 0]
        if _active:
            _total_bs = sum(_block_score(d) for d in duty_list)
            _rmin = min(s.effort_offset for s in _active)
            _rmax = max(s.effort_offset for s in _active) + max(s.effort_per_milli for s in _active) * _total_bs
            range_size = max(1, _rmax - _rmin)
            settings = dataclasses.replace(settings, effort_range_min=_rmin, effort_range_max=_rmax)

    if range_size > 0:
        range_min = settings.effort_range_min

        def _count_off(s: SoldierInput) -> int:
            return max(0, min(resolution, (s.effort_offset - range_min) * resolution // range_size))

        def _weight(s: SoldierInput, score_milli: int) -> int:
            return max(1, s.effort_per_milli * score_milli * resolution // range_size)

        total_ub = 2 * resolution + len(duty_list) + 1
    else:
        # All soldiers have effort_per_milli == 0 — pure covering problem, no fairness.
        def _count_off(s: SoldierInput) -> int:  # type: ignore[misc]
            return 0

        def _weight(s: SoldierInput, score_milli: int) -> int:  # type: ignore[misc]
            return 1

        total_ub = len(duty_list) + 1

    # We optimise over *eligible* soldiers only (those that can receive ≥1 duty).
    eligible_total_exprs: list[LinearExpr] = []  # count_offset + new weight per soldier
    eligible_offsets: list[int] = []             # count_offset constants
    # Secondary tiebreak (below L1) breaks L1's flat-region ties:
    #   • prior_terms = count_offset × new_count → prefer LOW-prior soldiers
    #   • count_spread (max−min of new counts) → split evenly among equals
    # Both are linear/cheap (no squares), so the model stays fast.
    prior_terms: list = []           # count_offset × new_count
    count_vars: list[IntVar] = []    # new-duty counts (for the even-split spread)
    total_new_weight = 0              # Σ over all duties of their unit weight (for μ)

    for si, s in enumerate(soldier_list):
        duties_for_s = soldier_duties.get(si, [])
        if not duties_for_s:
            continue

        count_offset = _count_off(s)
        new_weight = sum(
            _weight(s, _block_score(duty_list[di])) * x[(di, si)]
            for di in duties_for_s
        )
        eligible_total_exprs.append(count_offset + new_weight)
        eligible_offsets.append(count_offset)

        count = model.NewIntVar(0, len(duties_for_s), f"count_s{si}")
        model.Add(count == sum(x[(di, si)] for di in duties_for_s))
        count_vars.append(count)
        if count_offset:
            prior_terms.append(count_offset * count)

    # Total new weight that will be distributed (each duty goes to exactly one of
    # its eligible soldiers).  The per-duty weight depends on the assigned
    # soldier's per_milli, which we don't know yet; use the AVERAGE eligible
    # per_milli as the least-biased representative for the centre μ.  (Using max
    # would inflate μ and wrongly pull duties toward high-marginal soldiers.)
    for di, d in enumerate(duty_list):
        per_millis = [soldier_list[si].effort_per_milli for (dii, si) in eligible if dii == di]
        pm = sum(per_millis) // len(per_millis) if per_millis else 0
        bs = _block_score(d)
        if range_size > 0:
            total_new_weight += max(1, pm * bs * resolution // range_size)
        else:
            total_new_weight += 1  # pure covering: all weights = 1

    # Hard constraints: T (non-reserve duty-days) and R (all duty-days) per rolling
    # W-day window per soldier.  T <= R enforces the invariant; reserve days consume
    # R headroom but not T.  Inner loop uses binary search (bisect) so per-window
    # duty lookup is O(log m + matches) instead of O(m).
    existing_all_by_soldier = existing_dates_cache
    existing_real_by_soldier = existing_real_dates_cache

    for si, s in enumerate(soldier_list):
        si_duties = soldier_duties.get(si, [])
        existing_all = existing_all_by_soldier.get(s.id, set())
        existing_real = existing_real_by_soldier.get(s.id, set())

        if not si_duties and not existing_all:
            continue

        # Sort eligible duties by start_date for binary-search window lookup.
        si_duties_sorted = sorted(si_duties, key=lambda di: duty_list[di].start_date)
        starts_sorted: list[date] = [duty_list[di].start_date for di in si_duties_sorted]
        ends_sorted: list[date] = [duty_list[di].end_date for di in si_duties_sorted]

        all_relevant: set[date] = set(existing_all)
        for di in si_duties:
            all_relevant.add(duty_list[di].start_date)
            all_relevant.add(duty_list[di].end_date)
        if not all_relevant:
            continue

        min_d = min(all_relevant)
        max_d = max(all_relevant)
        sorted_existing_all = sorted(existing_all)
        sorted_existing_real = sorted(existing_real)

        # ── T cap: non-reserve duty-days per Wt-day rolling window ───────────
        ws = min_d
        while ws <= max_d:
            we = ws + timedelta(days=Wt - 1)
            existing_real_fixed = (
                bisect.bisect_right(sorted_existing_real, we)
                - bisect.bisect_left(sorted_existing_real, ws)
            )
            right = bisect.bisect_right(starts_sorted, we)
            vars_real: list[IntVar] = []
            for i in range(right):
                if ends_sorted[i] < ws:
                    continue
                di = si_duties_sorted[i]
                if not duty_list[di].is_reserve:
                    vars_real.append(x[(di, si)])
            if vars_real or existing_real_fixed:
                headroom_T = T - existing_real_fixed
                if headroom_T <= 0:
                    # Existing assignments already fill or exceed the T cap for
                    # this window. Blocking new duties keeps the model satisfiable
                    # (instead of adding an always-false constraint that makes the
                    # entire model infeasible and prevents assigning unrelated duties
                    # to other soldiers).
                    if vars_real:
                        model.Add(sum(vars_real) == 0)
                else:
                    model.Add(sum(vars_real) <= headroom_T)
            ws += timedelta(days=1)

        # ── R cap: all duty-days (reserve + real) per Wr-day rolling window ──
        ws = min_d
        while ws <= max_d:
            we = ws + timedelta(days=Wr - 1)
            existing_all_fixed = (
                bisect.bisect_right(sorted_existing_all, we)
                - bisect.bisect_left(sorted_existing_all, ws)
            )
            right = bisect.bisect_right(starts_sorted, we)
            vars_all: list[IntVar] = []
            for i in range(right):
                if ends_sorted[i] < ws:
                    continue
                di = si_duties_sorted[i]
                vars_all.append(x[(di, si)])
            if vars_all or existing_all_fixed:
                headroom_R = R - existing_all_fixed
                if headroom_R <= 0:
                    if vars_all:
                        model.Add(sum(vars_all) == 0)
                else:
                    model.Add(sum(vars_all) <= headroom_R)
            ws += timedelta(days=1)

    terms = FairnessTerms(
        eligible_total_exprs=eligible_total_exprs,
        eligible_offsets=eligible_offsets,
        total_new_weight=total_new_weight,
        prior_terms=prior_terms,
        count_vars=count_vars,
        total_ub=total_ub,
    )
    build_fairness_objective(model, x, duty_list, settings, reserve_dist, terms)

    if with_obj_terms:
        return model, x, terms
    return model, x
