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

from app.algorithm.types import (
    EFFORT_SCALE,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
)


def _block_score(d: DutyBlock) -> int:
    """Total score for completing the entire block, in milli-units (x1000 for integer math)."""
    days = (d.end_date - d.start_date).days
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
        count_w = 10_000        # 1e4 — above the per-move reserve-distance term
        n_elig = len(eligible_total_exprs)
        mu_const = (sum(eligible_offsets) + total_new_weight) // n_elig

        dev_terms: list[IntVar] = []
        for i, total in enumerate(eligible_total_exprs):
            dev = model.NewIntVar(0, total_ub, f"effort_dev{i}")
            model.Add(dev >= total - mu_const)
            model.Add(dev >= mu_const - total)
            dev_terms.append(dev)
        l1_term = sum(dev_terms)

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
            constrained_dates = constraint_map.get(s.id, set())
            if duty_dates_cache[di] & constrained_dates:
                continue
            if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
                if s.hierarchy_node_id not in d.eligible_node_ids:
                    continue
            eligible.append((di, si))
            soldier_duties[si].append(di)

    # Decision variables: x[di, si] = 1 if soldier si gets duty di
    x: dict[tuple[int, int], IntVar] = {}
    for di, si in eligible:
        x[(di, si)] = model.NewBoolVar(f"x_d{di}_s{si}")

    # Coverage constraint. Hard: every duty assigned to exactly one soldier
    # (model infeasible if any duty is unplaceable). Soft: each duty assigned to
    # at most one soldier, so unplaceable duties are simply left unselected and
    # the caller can defer them.
    for di in range(len(duty_list)):
        vars_for_d = [x[(di, si)] for (dii, si) in eligible if dii == di]
        if coverage == "soft":
            if vars_for_d:
                model.Add(sum(vars_for_d) <= 1)
        else:
            model.Add(sum(vars_for_d) == 1)

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
                model.Add(existing_real_fixed + sum(vars_real) <= T)
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
                model.Add(existing_all_fixed + sum(vars_all) <= R)
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
