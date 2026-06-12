from __future__ import annotations

import bisect
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

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
    days = (d.end_date - d.start_date).days + 1
    return int(d.score_per_day * Decimal(days) * 1000)


def _duty_dates(d: DutyBlock) -> list[date]:
    dt = d.start_date
    result: list[date] = []
    while dt <= d.end_date:
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
            while dt <= ea.end_date:
                result.add(dt)
                dt += timedelta(days=1)
    return result


def build_model(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
) -> tuple[CpModel, dict[tuple[int, int], IntVar]]:
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

    # Pre-filter eligible (duty, soldier) pairs
    eligible: list[tuple[int, int]] = []
    soldier_duties: dict[int, list[int]] = defaultdict(list)
    for di, d in enumerate(duty_list):
        for si, s in enumerate(soldier_list):
            if d.duty_type_id in exempt_map.get(s.id, set()):
                continue
            constrained_dates = constraint_map.get(s.id, set())
            if any(dt in constrained_dates for dt in _duty_dates(d)):
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

    # Hard constraint 1: Coverage — every duty assigned to exactly one soldier
    for di in range(len(duty_list)):
        vars_for_d = [x[(di, si)] for (dii, si) in eligible if dii == di]
        model.Add(sum(vars_for_d) == 1)

    # Hard constraint 2: No overlap — a soldier cannot be assigned two duties covering the same day
    all_dates_set: set[date] = set()
    for d in duty_list:
        all_dates_set.update(_duty_dates(d))

    for si, s in enumerate(soldier_list):
        existing_dates = _existing_dates_by_soldier(existing, s.id)
        for t in sorted(all_dates_set):
            day_vars = [x[(di, si)] for di in soldier_duties.get(si, [])
                        if _duty_dates(duty_list[di]).count(t) > 0]
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
    # objective below stays tractable:
    #
    #   DIV            = EFFORT_SCALE // effort_resolution      (K = resolution)
    #   count_offset_i = effort_offset_i // DIV                 (prior effort, a constant)
    #   weight_i(duty) = max(1, effort_per_milli_i × block_score(duty) // DIV)
    #   total_i        = count_offset_i + Σ_{assigned} weight_i(duty)
    #
    # effort_offset / effort_per_milli are injected by the bridge over the FULL
    # duty set (so per_milli is not inflated by a small subset).  Scaling by 1/DIV
    # only rounds away effort differences below 1/K — everything else (the W and
    # unit-score normalisation) stays baked in.  A reserve's block_score is already
    # standby_multiplier× its primary, so its weight is the same fraction; the
    # max(1, …) floor keeps a reserve worth ≥ 1 unit.
    div = max(1, EFFORT_SCALE // settings.effort_resolution)
    # Upper bound on count-space total: offset (≤ EFFORT_SCALE/DIV) plus the marginal
    # (sums to ≤ EFFORT_SCALE/DIV); pad for the per-duty floor rounding.
    total_ub = 4 * (EFFORT_SCALE // div) + len(duty_list) + 1

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

        count_offset = s.effort_offset // div
        new_weight = sum(
            max(1, (s.effort_per_milli * _block_score(duty_list[di])) // div) * x[(di, si)]
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
        total_new_weight += max(1, (pm * _block_score(d)) // div)

    # Hard constraints: T (non-reserve duty-days) and R (all duty-days) per rolling
    # W-day window per soldier.  T <= R enforces the invariant; reserve days consume
    # R headroom but not T.  Inner loop uses binary search (bisect) so per-window
    # duty lookup is O(log m + matches) instead of O(m).
    existing_all_by_soldier = {
        s.id: _existing_dates_by_soldier(existing, s.id) for s in soldier_list
    }
    existing_real_by_soldier = {
        s.id: _existing_dates_by_soldier(
            [e for e in existing if not e.is_reserve], s.id
        )
        for s in soldier_list
    }

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

    return model, x
