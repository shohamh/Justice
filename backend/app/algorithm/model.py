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

    if norm_exprs:
        min_norm = model.NewIntVar(0, 10_000_000, "min_norm")
        max_norm = model.NewIntVar(0, 10_000_000, "max_norm")
        model.AddMinEquality(min_norm, norm_exprs)
        model.AddMaxEquality(max_norm, norm_exprs)
        K_int = int(settings.K * 1000)
        model.Add(max_norm - min_norm <= K_int)

    # Density window tracking (variables kept for Task 4 hard constraint)
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

            if not var_for_window and existing_fixed <= T:
                ws += timedelta(days=1)
                continue

            total_density = existing_fixed + (sum(var_for_window) if var_for_window else 0)

            excess = model.NewIntVar(0, W, f"excess_s{si}_w{ws}")
            model.Add(excess >= total_density - T)
            model.Add(excess >= 0)

            # Piecewise-linear: 1x, 3x, 5x marginal costs
            # Cost minimisation naturally fills cheaper buckets first.
            e1 = model.NewIntVar(0, 1, f"e1_s{si}_w{ws}")
            e2 = model.NewIntVar(0, 2, f"e2_s{si}_w{ws}")
            e3 = model.NewIntVar(0, W, f"e3_s{si}_w{ws}")
            model.Add(e1 + e2 + e3 == excess)

            cost = e1 + 3 * e2 + 5 * e3  # noqa: F841 — kept for Task 4

            ws += timedelta(days=1)

    # Soft objective: hierarchy proximity for reserve blocks
    reserve_dist_terms: list = []
    if reserve_dist is not None:
        gamma_int = int(settings.reserve_hierarchy_weight * 1000)
        for (di, si), var in x.items():
            if duty_list[di].is_reserve:
                dist = reserve_dist.get((di, si), 10)
                reserve_dist_terms.append(gamma_int * dist * var)

    # Soft objective: prefer soldiers with lower pre-assignment normalised score
    alpha_int = int(settings.alpha * 1000)
    score_terms: list = []
    if alpha_int > 0:
        for (di, si), var in x.items():
            s = soldier_list[si]
            if s.active_days > 0:
                pre_norm = int(s.cumulative_score * 1000) // s.active_days
                score_terms.append(alpha_int * pre_norm * var)

    objective = (
        -(sum(reserve_dist_terms) if reserve_dist_terms else 0)
        - (sum(score_terms) if score_terms else 0)
    )
    model.Maximize(objective)
    return model, x
