from __future__ import annotations

import bisect
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from ortools.sat.python.cp_model import CpModel, IntVar, LinearExpr

from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings


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
    W = settings.W
    T = settings.T

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

    # ── Normalised-score expressions ─────────────────────────────────────────
    #
    # norm_s = (cumulative_score * 1000 + new_assignment_score) / active_days
    #
    # This represents the soldier's post-run score_per_day in milli-units.
    # It's the single fairness metric: we want all soldiers to converge toward
    # the same value over time.  Using cumulative (not incremental-only) ensures
    # the algorithm accounts for history: a soldier already at spd=0.5 gets no
    # new duties while one at spd=0 gets many, even if their incremental load
    # would be equal.

    # Eligible-only norms for the "raise the floor" secondary objective.
    # Soldiers with no eligible duties always have norm = historical base and
    # cannot be improved; including them would pin the floor unnecessarily.
    all_norm_exprs: list[LinearExpr] = []
    eligible_norm_exprs: list[LinearExpr] = []
    # Historical tiebreaker: cost of assigning to a soldier with high spd.
    # Uses score_per_day (not raw cumulative_score) so a soldier with 10 pts
    # over 200 days (spd=0.05) is correctly preferred over one with 10 pts
    # over 100 days (spd=0.10).
    hist_penalty_terms: list = []

    for si, s in enumerate(soldier_list):
        if s.active_days == 0:
            continue

        duties_for_s = soldier_duties.get(si, [])
        block_sum = sum(
            _block_score(duty_list[di]) * x[(di, si)]
            for di in duties_for_s
        )

        base = int(s.cumulative_score * 1000)
        cum_total = base + block_sum
        norm = model.NewIntVar(0, 10_000_000, f"norm_s{si}")
        model.AddDivisionEquality(norm, cum_total, s.active_days)
        all_norm_exprs.append(norm)

        if duties_for_s:
            eligible_norm_exprs.append(norm)

        # hist_milli = score_per_day in milli-units (an integer constant, not a variable)
        hist_milli = int(s.cumulative_score * 1000) // s.active_days
        for di in duties_for_s:
            hist_penalty_terms.append(hist_milli * x[(di, si)])

    max_norm_var = None
    if all_norm_exprs:
        max_norm_var = model.NewIntVar(0, 10_000_000, "max_norm")
        model.AddMaxEquality(max_norm_var, all_norm_exprs)

    # Hard constraint: max T duty-days in any rolling W-day window per soldier
    #
    # Inner loop uses binary search (bisect) so per-window duty lookup is
    # O(log m + matches) instead of O(m).  Overall complexity drops from
    # O(n × date_range × m) to O(n × date_range × log m), which makes
    # large instances (n≈100, m≈200) feasible.
    existing_by_soldier = {
        s.id: _existing_dates_by_soldier(existing, s.id) for s in soldier_list
    }

    for si, s in enumerate(soldier_list):
        si_duties = soldier_duties.get(si, [])
        existing_dates = existing_by_soldier.get(s.id, set())

        if not si_duties and not existing_dates:
            continue

        # Sort eligible duties by start_date for binary-search window lookup.
        # A duty overlaps window [ws, we] iff start_date ≤ we AND end_date ≥ ws.
        si_duties_sorted = sorted(si_duties, key=lambda di: duty_list[di].start_date)
        starts_sorted: list[date] = [duty_list[di].start_date for di in si_duties_sorted]
        ends_sorted: list[date] = [duty_list[di].end_date for di in si_duties_sorted]

        # Date range: span of all eligible duty dates plus any existing dates
        all_relevant: set[date] = set(existing_dates)
        for di in si_duties:
            all_relevant.add(duty_list[di].start_date)
            all_relevant.add(duty_list[di].end_date)
        if not all_relevant:
            continue

        min_d = min(all_relevant)
        max_d = max(all_relevant)
        sorted_existing = sorted(existing_dates)

        ws = min_d
        while ws <= max_d:
            we = ws + timedelta(days=W - 1)

            # Count pre-fixed existing duty-days in this window
            existing_fixed = (
                bisect.bisect_right(sorted_existing, we)
                - bisect.bisect_left(sorted_existing, ws)
            )

            # Find variable duties overlapping [ws, we] via binary search:
            #   start_date ≤ we  →  right = bisect_right(starts, we)
            #   end_date ≥ ws   →  linear scan only the filtered prefix
            # For short-duration duties the filtered list is tiny.
            right = bisect.bisect_right(starts_sorted, we)
            var_for_window: list[IntVar] = [
                x[(si_duties_sorted[i], si)]
                for i in range(right)
                if ends_sorted[i] >= ws
            ]

            if not var_for_window:
                ws += timedelta(days=1)
                continue

            model.Add(existing_fixed + sum(var_for_window) <= T)
            ws += timedelta(days=1)

    # Soft objective: hierarchy proximity for reserve blocks
    reserve_dist_terms: list = []
    if reserve_dist is not None:
        gamma_int = int(settings.reserve_hierarchy_weight * 1000)
        for (di, si), var in x.items():
            if duty_list[di].is_reserve:
                dist = reserve_dist.get((di, si), 10)
                reserve_dist_terms.append(gamma_int * dist * var)

    # ── Fairness objective ──────────────────────────────────────────────────
    #
    # Fairness goal: all soldiers converge toward the same score_per_day
    # (norm = cumulative_score / active_days).
    #
    # PRIMARY  (weight alpha_int ≈ 1000):
    #   Minimise max(norm).  Assigning a duty to an already-high-norm soldier
    #   raises max; assigning to a low-norm soldier leaves max unchanged.
    #   This naturally steers duties toward lower-norm soldiers.
    #
    # SECONDARY  (weight 1, ≈1000× weaker than primary):
    #   Maximise min(norm) among eligible soldiers.  When the primary is tied
    #   (e.g. the max is already pinned by a high-history soldier), this lifts
    #   the floor — giving extra duties to the lowest-norm soldiers first rather
    #   than concentrating them arbitrarily.
    #
    # TIEBREAKER  (weight 1, proportional to hist_milli per assignment):
    #   When both primary and secondary are tied, prefer assigning to the soldier
    #   with the lower historical score_per_day.  Uses score/day not raw score
    #   so active_days is correctly accounted for.
    #
    # RESERVE PROXIMITY  (weight gamma_int):
    #   Minor bonus for pairing reserves with geographically close primaries.
    # ────────────────────────────────────────────────────────────────────────

    alpha_int = int(settings.alpha * 1000)
    dist_term = sum(reserve_dist_terms) if reserve_dist_terms else 0
    hist_penalty = sum(hist_penalty_terms) if hist_penalty_terms else 0

    if max_norm_var is not None and alpha_int > 0:
        min_term = 0
        if len(eligible_norm_exprs) > 1:
            min_norm_var = model.NewIntVar(0, 10_000_000, "min_norm_eligible")
            model.AddMinEquality(min_norm_var, eligible_norm_exprs)
            min_term = min_norm_var

        model.Maximize(-alpha_int * max_norm_var + min_term - hist_penalty - dist_term)
    else:
        model.Maximize(-dist_term)

    return model, x
