from __future__ import annotations

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

    # Hard constraint 3: K normalised-score variance
    norm_exprs: list[LinearExpr] = []
    for si, s in enumerate(soldier_list):
        if s.active_days == 0:
            continue
        block_sum = sum(
            _block_score(duty_list[di]) * x[(di, si)]
            for di in soldier_duties.get(si, [])
        )
        base = int(s.cumulative_score * 1000)
        total = base + block_sum
        norm = model.NewIntVar(0, 10_000_000, f"norm_s{si}")
        model.AddDivisionEquality(norm, total, s.active_days)
        norm_exprs.append(norm)

    max_norm_var = None
    if norm_exprs:
        min_norm = model.NewIntVar(0, 10_000_000, "min_norm")
        max_norm_var = model.NewIntVar(0, 10_000_000, "max_norm")
        model.AddMinEquality(min_norm, norm_exprs)
        model.AddMaxEquality(max_norm_var, norm_exprs)
        K_int = int(settings.K * 1000)
        model.Add(max_norm_var - min_norm <= K_int)

    # Hard constraint: max T duty-days in any rolling W-day window per soldier
    existing_by_soldier = {
        s.id: _existing_dates_by_soldier(existing, s.id) for s in soldier_list
    }

    for si, s in enumerate(soldier_list):
        soldier_dates_set = set(existing_by_soldier.get(s.id, set()))
        for di in soldier_duties.get(si, []):
            soldier_dates_set.update(_duty_dates(duty_list[di]))
        if not soldier_dates_set:
            continue

        min_d = min(soldier_dates_set)
        max_d = max(soldier_dates_set)
        existing_dates = existing_by_soldier.get(s.id, set())
        ws = min_d
        while ws <= max_d:
            we = ws + timedelta(days=W - 1)
            existing_fixed = sum(1 for dt_iter in existing_dates if ws <= dt_iter <= we)
            var_for_window: list[IntVar] = []
            for di in soldier_duties.get(si, []):
                d = duty_list[di]
                if any(ws <= dt <= we for dt in _duty_dates(d)):
                    var_for_window.append(x[(di, si)])

            if not var_for_window:
                ws += timedelta(days=1)
                continue

            total_density = existing_fixed + (sum(var_for_window) if var_for_window else 0)
            model.Add(total_density <= T)
            ws += timedelta(days=1)

    # Soft objective: hierarchy proximity for reserve blocks
    reserve_dist_terms: list = []
    if reserve_dist is not None:
        gamma_int = int(settings.reserve_hierarchy_weight * 1000)
        for (di, si), var in x.items():
            if duty_list[di].is_reserve:
                dist = reserve_dist.get((di, si), 10)
                reserve_dist_terms.append(gamma_int * dist * var)

    # Primary fairness objective: minimise the maximum post-assignment normalised score.
    # This is strictly better than the previous "minimise sum of pre-assignment scores"
    # approach, which was blind when all soldiers start at zero and provided no
    # differentiation between soldiers within a single run.
    alpha_int = int(settings.alpha * 1000)
    dist_term = sum(reserve_dist_terms) if reserve_dist_terms else 0

    if max_norm_var is not None and alpha_int > 0:
        # Minimize the maximum post-assignment normalised score (in milli-score/day).
        # max_norm_var typical range: 0–10 000 for realistic units.
        # alpha_int typical value: 1000 (alpha = 1.0).
        # reserve_dist_terms total: up to ~50 000 for large units.
        # The fairness term dominates (10–100×), making reserve proximity a tiebreaker.
        # Both are plain LinearExpr — no Python-level division needed.
        model.Maximize(-alpha_int * max_norm_var - dist_term)
    else:
        model.Maximize(-dist_term)

    return model, x
