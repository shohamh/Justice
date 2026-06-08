# backend/app/services/effort_score.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.services.scoring import effective_duty_days

# Scale factor for converting Decimal effort scores to CP-SAT integers.
# effort_offset = int(effort_score × EFFORT_SCALE)
# effort_per_milli = int(C_over_D / unit_score_milli × EFFORT_SCALE)
EFFORT_SCALE = 1_000_000_000  # 10^9


@dataclass
class EffortData:
    """Per-soldier effort computation result for use in the CP-SAT model."""
    effort_score: Decimal      # A_i / D_i: historical weighted-average quarterly share
    C_over_D: Decimal          # C_i / D_i: current-window weight over total weight
    effort_offset: int = 0     # int(effort_score × EFFORT_SCALE) — precomputed for model
    effort_per_milli: int = 0  # int(C_over_D / unit_score_milli × EFFORT_SCALE) — set by bridge


def quarter_start(d: date) -> date:
    """Return the first day of the calendar quarter containing d."""
    month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, month, 1)


def quarter_end(d: date) -> date:
    """Return the last day of the calendar quarter containing d."""
    qs = quarter_start(d)
    if qs.month >= 10:
        return date(qs.year, 12, 31)
    return date(qs.year, qs.month + 3, 1) - timedelta(days=1)


def _compute_effort_data(
    *,
    soldiers: list[Any],   # objects with .id (UUID) and .enrolled_at (date)
    quarters: list[tuple[date, date]],
    quarter_unit_scores: dict[date, Decimal],   # keyed by quarter_start date
    quarter_soldier_scores: dict[date, dict[uuid.UUID, Decimal]],  # keyed by quarter_start date
    planning_start: date,
    planning_end: date,
) -> dict[uuid.UUID, EffortData]:
    """
    Pure-logic core: compute EffortData per soldier given pre-aggregated quarter scores.

    quarters: list of (q_start, q_end) in ascending order.
    quarter_unit_scores: total unit score per quarter, keyed by q_start.
    quarter_soldier_scores: per-soldier scores per quarter, keyed by q_start.
    """
    planning_days = (planning_end - planning_start).days + 1
    result: dict[uuid.UUID, EffortData] = {}

    for soldier in soldiers:
        A_i = Decimal("0")  # numerator: sum(share_q × active_frac_q)
        W_i = Decimal("0")  # denominator: sum(active_frac_q)

        for q_start, q_end in quarters:
            q_days = (q_end - q_start).days + 1
            soldier_start = max(soldier.enrolled_at, q_start)
            if soldier_start > q_end:
                continue  # soldier not enrolled in this quarter

            active_in_q = (q_end - soldier_start).days + 1
            active_frac = Decimal(active_in_q) / Decimal(q_days)

            unit_score = quarter_unit_scores.get(q_start, Decimal("0"))
            if unit_score > 0:
                s_score = quarter_soldier_scores.get(q_start, {}).get(soldier.id, Decimal("0"))
                share_q = s_score / unit_score
                A_i += share_q * active_frac

            # Count the quarter in W_i regardless of whether unit had duties
            W_i += active_frac

        # Current planning window contribution
        sol_plan_start = max(soldier.enrolled_at, planning_start)
        if sol_plan_start <= planning_end:
            sol_planning_days = (planning_end - sol_plan_start).days + 1
            C_i = Decimal(sol_planning_days) / Decimal(planning_days)
        else:
            C_i = Decimal("0")

        D_i = W_i + C_i
        if D_i <= 0:
            result[soldier.id] = EffortData(
                effort_score=Decimal("0"), C_over_D=Decimal("0"),
                effort_offset=0, effort_per_milli=0,
            )
            continue

        effort_score = A_i / D_i
        C_over_D = C_i / D_i
        effort_offset = int(effort_score * EFFORT_SCALE)

        result[soldier.id] = EffortData(
            effort_score=effort_score,
            C_over_D=C_over_D,
            effort_offset=effort_offset,
            effort_per_milli=0,  # set by bridge after unit_score_milli is known
        )

    return result


def compute_effort_data(
    session: Session,
    *,
    soldiers: list[Any],    # objects with .id (UUID) and .enrolled_at (date)
    planning_start: date,
    planning_end: date,
    reset_date: date,
) -> dict[uuid.UUID, EffortData]:
    """
    Compute EffortData for all soldiers using published assignment history.

    Uses effective_duty_days() from scoring.py (same source-of-truth as score calculations).
    Loads history from reset_date up to (but not including) planning_start.

    Returns dict[soldier_id, EffortData] with effort_per_milli=0;
    the caller (bridge) sets effort_per_milli after knowing unit_score_milli.
    """
    from sqlalchemy import select
    from app.db.models import DutyType

    history_end = planning_start - timedelta(days=1)
    if history_end < reset_date:
        # No historical data — all soldiers start fresh
        return _compute_effort_data(
            soldiers=soldiers,
            quarters=[],
            quarter_unit_scores={},
            quarter_soldier_scores={},
            planning_start=planning_start,
            planning_end=planning_end,
        )

    # Build list of complete quarters between reset_date and planning_start.
    # Clip the first quarter's start to reset_date so active_frac is only
    # counted from when we have actual duty data (avoids inflating W_i for
    # soldiers enrolled before reset_date when reset falls mid-quarter).
    quarters = []
    q_s = quarter_start(reset_date)
    while q_s < planning_start:
        q_e = quarter_end(q_s)
        actual_start = max(q_s, reset_date)
        actual_end = min(q_e, history_end)
        quarters.append((actual_start, actual_end))
        # Advance to next quarter
        next_month = q_e + timedelta(days=1)
        q_s = next_month

    if not quarters:
        return _compute_effort_data(
            soldiers=soldiers,
            quarters=[],
            quarter_unit_scores={},
            quarter_soldier_scores={},
            planning_start=planning_start,
            planning_end=planning_end,
        )

    # Fetch duty type scores
    dt_scores: dict[uuid.UUID, Decimal] = {
        dt.id: dt.score_per_day
        for dt in session.execute(select(DutyType)).scalars().all()
    }

    # Expand published assignments to per-day rows, filtered to history range
    days_data = effective_duty_days(session, date_from=reset_date, date_to=history_end)

    # Map each calendar date to its quarter_start
    date_to_quarter: dict[date, date] = {}
    for q_start_d, q_end_d in quarters:
        d = q_start_d
        while d <= q_end_d:
            date_to_quarter[d] = q_start_d
            d += timedelta(days=1)

    # Aggregate scores per quarter
    q_unit_scores: dict[date, Decimal] = {}
    q_soldier_scores: dict[date, dict[uuid.UUID, Decimal]] = {}
    for day, soldier_id, duty_type_id, mult in days_data:
        qs = date_to_quarter.get(day)
        if qs is None:
            continue
        score = dt_scores.get(duty_type_id, Decimal("0")) * mult
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + score
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[soldier_id] = q_s_map.get(soldier_id, Decimal("0")) + score

    return _compute_effort_data(
        soldiers=soldiers,
        quarters=quarters,
        quarter_unit_scores=q_unit_scores,
        quarter_soldier_scores=q_soldier_scores,
        planning_start=planning_start,
        planning_end=planning_end,
    )
