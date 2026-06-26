# backend/app/services/effort_score.py
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.algorithm.duration import calendar_days_touched, score_days
from app.algorithm.types import EFFORT_SCALE  # noqa: F401  (re-exported for importers)
from app.services.scoring import effective_duty_days


@dataclass
class EffortData:
    """Per-soldier effort computation result for use in the CP-SAT model."""
    effort_score: Decimal      # A_i / D_i: historical weighted-average quarterly share
    C_over_D: Decimal          # C_i / D_i: current-window weight over total weight
    effort_offset: int = 0     # int(effort_score × EFFORT_SCALE) — precomputed for model
    effort_per_milli: int = 0  # int(C_over_D / unit_score_milli × EFFORT_SCALE) — set by bridge


@dataclass
class EffortQuarterDetail:
    """Per-quarter breakdown for a single soldier."""
    quarter_start: date
    quarter_end: date
    quarter_label: str       # e.g. "Q1 2026"
    soldier_score: Decimal   # raw score earned by soldier in this quarter (duties + adjustments)
    unit_score: Decimal      # total unit score in this quarter (duties + adjustments)
    active_frac: Decimal     # fraction of quarter soldier was active (0.0–1.0)
    share: Decimal           # soldier_score / unit_score (0 if unit had no duties)
    weighted_share: Decimal  # share × active_frac
    is_partial: bool = False # True if quarter end was clipped (still in progress)
    adjustment_delta: Decimal = field(default_factory=lambda: Decimal("0"))  # sum of manual score adjustments in this quarter


@dataclass
class EffortBreakdown:
    """Full per-quarter breakdown for one soldier, plus the aggregate result."""
    quarters: list[EffortQuarterDetail] = field(default_factory=list)
    effort_score: Decimal = Decimal("0")
    # Raw components: effort_score = A_i / W_i
    A_i: Decimal = Decimal("0")   # Σ(share_q × active_frac_q)
    W_i: Decimal = Decimal("0")   # Σ(active_frac_q)  — historical weight


def _quarter_label(q_start: date) -> str:
    """Return human-readable quarter label, e.g. 'Q1 2026'."""
    q = (q_start.month - 1) // 3 + 1
    return f"Q{q} {q_start.year}"


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


def _find_quarter_key(all_quarters: list[tuple[date, date]], d: date) -> date | None:
    """
    Return the q_start_d key (possibly clipped) for the calendar quarter containing d.
    Returns None if d does not fall in any of the tracked quarters.
    """
    target = quarter_start(d)
    for q_start_d, _ in all_quarters:
        if quarter_start(q_start_d) == target:
            return q_start_d
    return None


def _pending_quarter_scores(pending_duties: Sequence[Any]) -> dict[date, Decimal]:
    """Apportion each pending (not-yet-published) duty's total score across the
    calendar quarter(s) it falls in, using the same per-day weighting
    `effective_duty_days` uses for published assignments (score_days /
    days_touched per calendar day touched). Keyed by the UNCLIPPED calendar
    quarter_start -- these duties haven't happened yet, so there is no history
    boundary to clip against.

    Used by `compute_effort_data`'s `pending_duties` parameter to inflate a
    quarter's unit_score by the workload the algorithm is about to assign this
    run, assuming it ends up fully covered.
    """
    buckets: dict[date, Decimal] = {}
    for d in pending_duties:
        touched = calendar_days_touched(d.start_date, d.end_date)
        if touched <= 0:
            continue
        day_weight = Decimal(score_days(d.start_date, d.end_date, d.start_time, d.end_time)) / Decimal(touched)
        per_day_score = Decimal(d.score_per_day) * day_weight
        day = d.start_date
        while day < d.end_date:
            qs = quarter_start(day)
            buckets[qs] = buckets.get(qs, Decimal("0")) + per_day_score
            day += timedelta(days=1)
    return buckets


def _compute_effort_data(
    *,
    soldiers: list[Any],   # objects with .id (UUID) and .enrolled_at (date)
    quarters: list[tuple[date, date]],
    quarter_unit_scores: dict[date, Decimal],   # keyed by quarter_start date
    quarter_soldier_scores: dict[date, dict[uuid.UUID, Decimal]],  # keyed by quarter_start date
) -> dict[uuid.UUID, EffortData]:
    """
    Pure-logic core: compute EffortData per soldier given pre-aggregated quarter scores.

    effort_score = A_i / W_i  (historical weighted-average share; 0 for new soldiers)
    C_over_D     = 1 / max(W_i, 1)  — used by the bridge to compute effort_per_milli.
    """
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
                W_i += active_frac

        effective_W = W_i if W_i > Decimal("0") else Decimal("1")
        effort_score = A_i / W_i if W_i > Decimal("0") else Decimal("0")
        C_over_D = Decimal("1") / effective_W
        effort_offset = int(effort_score * EFFORT_SCALE)

        result[soldier.id] = EffortData(
            effort_score=effort_score,
            C_over_D=C_over_D,
            effort_offset=effort_offset,
            effort_per_milli=0,  # set by bridge after unit_score_milli is known
        )

    return result


def _build_future_quarters(
    days_data: list[tuple[date, uuid.UUID, uuid.UUID, Decimal]],
    planning_end: date,
) -> list[tuple[date, date]]:
    """
    Given per-day rows from effective_duty_days, return a list of (q_start, q_end)
    tuples for all calendar quarters that contain dates strictly after planning_end.
    Returns an empty list if there are no such dates.
    """
    future_dates = [day for day, _sid, _dtid, _mult in days_data if day > planning_end]
    if not future_dates:
        return []

    min_future = min(future_dates)
    max_future = max(future_dates)

    future_quarters: list[tuple[date, date]] = []
    q_s = quarter_start(min_future)
    while q_s <= max_future:
        q_e = quarter_end(q_s)
        future_quarters.append((q_s, q_e))
        q_s = q_e + timedelta(days=1)

    return future_quarters


def compute_effort_data(
    session: Session,
    *,
    soldiers: list[Any],    # objects with .id (UUID) and .enrolled_at (date)
    planning_start: date,
    planning_end: date,
    reset_date: date,
    pending_duties: Sequence[Any] = (),  # DutyBlock-like: about to be planned, not yet published
) -> dict[uuid.UUID, EffortData]:
    """
    Compute EffortData for all soldiers using published assignment history plus
    any manual score adjustments (ScoreAdjustment records).

    Uses effective_duty_days() from scoring.py (same source-of-truth as score calculations).
    Loads history from reset_date up to (but not including) planning_start, PLUS any
    published assignments after planning_end (future duties beyond the planning window).

    `pending_duties` are duties the algorithm is ABOUT TO assign this run (not yet
    published). Each one's score is added to whichever quarter(s) it falls in, as if
    that quarter will end up fully covered -- WITHOUT crediting it to any soldier
    (nobody has been assigned it yet). This stops a quarter that currently has only
    a handful of published duties from looking like a soldier's huge personal share
    of it, when the algorithm is about to multiply that quarter's true total many
    times over. Leave empty for callers with nothing pending (e.g. the transparency
    page), where actual published history is the only honest signal.

    Returns dict[soldier_id, EffortData] with effort_per_milli=0;
    the caller (bridge) sets effort_per_milli after knowing unit_score_milli.
    """
    from sqlalchemy import select
    from app.db.models import DutyType, ScoreAdjustment

    history_end = planning_start - timedelta(days=1)

    # Build list of past quarters (reset_date → planning_start-1), clipping first quarter
    # start to reset_date so active_frac is only counted from when we have actual duty data.
    past_quarters: list[tuple[date, date]] = []
    if history_end >= reset_date:
        q_s = quarter_start(reset_date)
        while q_s < planning_start:
            q_e = quarter_end(q_s)
            actual_start = max(q_s, reset_date)
            actual_end = min(q_e, history_end)
            past_quarters.append((actual_start, actual_end))
            next_month = q_e + timedelta(days=1)
            q_s = next_month

    # Fetch ALL published duties from reset_date onwards (covers past and future)
    days_data = effective_duty_days(session, date_from=reset_date, date_to=date(2099, 12, 31))

    # Build future quarters from dates after planning_end
    future_quarters = _build_future_quarters(days_data, planning_end)

    all_quarters = past_quarters + future_quarters

    # Merge the about-to-be-assigned workload into whichever quarter(s) it falls
    # in (creating a new unclipped quarter tuple if none is tracked yet -- e.g. a
    # fresh future quarter with no published history at all). Computed before the
    # "anything to do" check below since pending-only duties can be the only
    # reason a quarter exists.
    cal_to_tracked: dict[date, date] = {quarter_start(q_s): q_s for q_s, _ in all_quarters}
    pending_unit_scores: dict[date, Decimal] = {}
    if pending_duties:
        for cal_qs, amount in _pending_quarter_scores(pending_duties).items():
            tracked_qs = cal_to_tracked.get(cal_qs)
            if tracked_qs is None:
                tracked_qs = cal_qs
                all_quarters.append((cal_qs, quarter_end(cal_qs)))
                cal_to_tracked[cal_qs] = cal_qs
            pending_unit_scores[tracked_qs] = pending_unit_scores.get(tracked_qs, Decimal("0")) + amount

    if not all_quarters:
        return _compute_effort_data(
            soldiers=soldiers,
            quarters=[],
            quarter_unit_scores={},
            quarter_soldier_scores={},
        )

    # Fetch duty type scores
    dt_scores: dict[uuid.UUID, Decimal] = {
        dt.id: dt.score_per_day
        for dt in session.execute(select(DutyType)).scalars().all()
    }

    # Map calendar-quarter-start → clipped quarter-start used in all_quarters.
    # O(Q) instead of O(Q × 90 days) — the per-day loop was building ~720 entries
    # only to do a dict lookup that quarter_start() computes directly.
    cal_qs_to_clipped: dict[date, date] = {
        quarter_start(q_start_d): q_start_d for q_start_d, _ in all_quarters
    }

    # Aggregate duty scores per quarter, seeded with the pending-workload baseline.
    q_unit_scores: dict[date, Decimal] = dict(pending_unit_scores)
    q_soldier_scores: dict[date, dict[uuid.UUID, Decimal]] = {}
    for day, soldier_id, duty_type_id, mult in days_data:
        # Skip the planning window — solver controls those
        if planning_start <= day <= planning_end:
            continue
        qs = cal_qs_to_clipped.get(quarter_start(day))
        if qs is None:
            continue
        score = dt_scores.get(duty_type_id, Decimal("0")) * mult
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + score
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[soldier_id] = q_s_map.get(soldier_id, Decimal("0")) + score

    # Include manual score adjustments in effort calculation
    adj_rows = session.execute(select(ScoreAdjustment)).scalars().all()
    for adj in adj_rows:
        qs = _find_quarter_key(all_quarters, adj.created_at.date())
        if qs is None:
            continue
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + adj.delta
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[adj.soldier_id] = q_s_map.get(adj.soldier_id, Decimal("0")) + adj.delta

    return _compute_effort_data(
        soldiers=soldiers,
        quarters=all_quarters,
        quarter_unit_scores=q_unit_scores,
        quarter_soldier_scores=q_soldier_scores,
    )


def compute_effort_breakdown(
    session: Session,
    *,
    soldier: Any,   # object with .id (UUID) and .enrolled_at (date)
    planning_start: date,
    planning_end: date,
    reset_date: date,
    extra_adj_delta: Decimal = Decimal("0"),
    extra_adj_date: date | None = None,
) -> EffortBreakdown:
    """
    Compute a full per-quarter effort breakdown for a single soldier.

    Includes manual score adjustments (ScoreAdjustment records) in the calculation.
    Pass extra_adj_delta + extra_adj_date to simulate a hypothetical future adjustment
    (used by the preview endpoint).

    Returns EffortBreakdown with one EffortQuarterDetail per historical quarter
    (past and future beyond planning window) plus the aggregate effort_score and C_over_D.
    """
    from sqlalchemy import select
    from app.db.models import DutyType, ScoreAdjustment

    history_end = planning_start - timedelta(days=1)

    # Past quarters (reset_date → planning_start-1), clipped to reset_date.
    past_quarters: list[tuple[date, date]] = []
    if history_end >= reset_date:
        q_s = quarter_start(reset_date)
        while q_s < planning_start:
            q_e = quarter_end(q_s)
            actual_start = max(q_s, reset_date)
            actual_end = min(q_e, history_end)
            past_quarters.append((actual_start, actual_end))
            q_s = q_e + timedelta(days=1)

    # Fetch ALL published duties from reset_date onwards (covers past and future),
    # then derive future quarters the SAME way compute_effort_data does, so the
    # breakdown's quarters and effort_score match the algorithm's exactly.
    days_data = effective_duty_days(session, date_from=reset_date, date_to=date(2099, 12, 31))
    future_quarters = _build_future_quarters(days_data, planning_end)
    quarters = past_quarters + future_quarters

    if not quarters:
        return EffortBreakdown(quarters=[], effort_score=Decimal("0"), A_i=Decimal("0"), W_i=Decimal("0"))

    # Fetch duty type scores
    dt_scores: dict[uuid.UUID, Decimal] = {
        dt.id: dt.score_per_day
        for dt in session.execute(select(DutyType)).scalars().all()
    }

    # Map calendar-quarter-start → clipped quarter-start (O(Q) instead of O(Q × 90 days))
    cal_qs_to_clipped: dict[date, date] = {
        quarter_start(q_start_d): q_start_d for q_start_d, _ in quarters
    }

    # Aggregate duty scores per quarter
    q_unit_scores: dict[date, Decimal] = {}
    q_soldier_scores: dict[date, dict[uuid.UUID, Decimal]] = {}
    for day, s_id, duty_type_id, mult in days_data:
        # Skip the planning window — solver controls those
        if planning_start <= day <= planning_end:
            continue
        qs = cal_qs_to_clipped.get(quarter_start(day))
        if qs is None:
            continue
        score = dt_scores.get(duty_type_id, Decimal("0")) * mult
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + score
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[s_id] = q_s_map.get(s_id, Decimal("0")) + score

    # Include manual score adjustments for this soldier
    q_adj_scores: dict[date, Decimal] = {}
    adj_rows = session.execute(
        select(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier.id)
    ).scalars().all()
    for adj in adj_rows:
        qs = _find_quarter_key(quarters, adj.created_at.date())
        if qs is None:
            continue
        q_adj_scores[qs] = q_adj_scores.get(qs, Decimal("0")) + adj.delta
        q_unit_scores[qs] = q_unit_scores.get(qs, Decimal("0")) + adj.delta
        q_s_map = q_soldier_scores.setdefault(qs, {})
        q_s_map[soldier.id] = q_s_map.get(soldier.id, Decimal("0")) + adj.delta

    # Apply hypothetical extra adjustment (for preview simulation)
    if extra_adj_delta and extra_adj_date is not None:
        extra_qs = _find_quarter_key(quarters, extra_adj_date)
        if extra_qs is not None:
            q_adj_scores[extra_qs] = q_adj_scores.get(extra_qs, Decimal("0")) + extra_adj_delta
            q_unit_scores[extra_qs] = q_unit_scores.get(extra_qs, Decimal("0")) + extra_adj_delta
            q_s_map = q_soldier_scores.setdefault(extra_qs, {})
            q_s_map[soldier.id] = q_s_map.get(soldier.id, Decimal("0")) + extra_adj_delta

    # Compute per-quarter detail for this soldier
    quarter_details: list[EffortQuarterDetail] = []
    A_i = Decimal("0")
    W_i = Decimal("0")

    for q_start_d, q_end_d in quarters:
        q_days = (q_end_d - q_start_d).days + 1
        soldier_start = max(soldier.enrolled_at, q_start_d)
        if soldier_start > q_end_d:
            continue  # not enrolled in this quarter

        active_in_q = (q_end_d - soldier_start).days + 1
        active_frac = Decimal(active_in_q) / Decimal(q_days)

        unit_score = q_unit_scores.get(q_start_d, Decimal("0"))
        s_score = q_soldier_scores.get(q_start_d, {}).get(soldier.id, Decimal("0"))
        share = s_score / unit_score if unit_score > 0 else Decimal("0")
        weighted_share = share * active_frac

        if unit_score > 0:
            A_i += weighted_share
            W_i += active_frac

        true_q_end = quarter_end(q_start_d)
        quarter_details.append(EffortQuarterDetail(
            quarter_start=q_start_d,
            quarter_end=q_end_d,
            quarter_label=_quarter_label(q_start_d),
            soldier_score=s_score,
            unit_score=unit_score,
            active_frac=active_frac,
            share=share,
            weighted_share=weighted_share,
            is_partial=(q_end_d < true_q_end),
            adjustment_delta=q_adj_scores.get(q_start_d, Decimal("0")),
        ))

    effort_score = A_i / W_i if W_i > Decimal("0") else Decimal("0")

    return EffortBreakdown(
        quarters=quarter_details,
        effort_score=effort_score,
        A_i=A_i,
        W_i=W_i,
    )
