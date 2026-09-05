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
    effort_score: Decimal      # A_i / W_i: Σ(s_q × w_q) / Σ(U_q × w_q) — scale-invariant cumulative ratio
    C_over_D: Decimal          # 1 / (W_i × 1000) — used by bridge as: effort_per_milli = int(C_over_D × EFFORT_SCALE)
    effort_offset: int = 0     # int(effort_score × EFFORT_SCALE) — precomputed for model
    effort_per_milli: int = 0  # int(C_over_D × EFFORT_SCALE) — set by bridge


@dataclass
class BurdenShareQuarterDetail:
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
    # Line items explaining how soldier_score was built: the published duty
    # spans credited to this soldier in this quarter plus manual adjustments.
    contributions: list["BurdenShareContribution"] = field(default_factory=list)


@dataclass
class BurdenShareContribution:
    """One traceable line item behind a quarter's soldier_score."""
    kind: str                # "duty" or "adjustment"
    label: str               # duty type name / adjustment reason
    score: Decimal           # points this item contributed to soldier_score
    detail: str = ""         # multiplier provenance note, e.g. reserve standby
    start_date: date | None = None  # first counted day (duty) — inclusive
    end_date: date | None = None    # last counted day (duty) — inclusive
    days: int = 0            # counted days in this quarter
    multiplier: Decimal = field(default_factory=lambda: Decimal("1"))  # average effective day multiplier


_MULTIPLIER_SOURCE_LABELS = {
    "default": "",
    "reserve_standby": "מקדם רזרבה — כוננות",
    "reserve_called_up": "מקדם רזרבה — צו 8",
    "dismissal": "ימי שחרור (מקדם מופחת)",
    "forced_call_up": "מקדם צו כפוי",
}


def compute_quarter_contributions(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    quarters: set[date],
) -> dict[date, list[BurdenShareContribution]]:
    """Traceability for the burden-share breakdown: per calendar-quarter-start, the
    published duty spans credited to `soldier_id` (via effective-soldier
    resolution — overrides/dismissals included) and the manual score
    adjustments booked to them. Duty scores use exactly the same day-expansion
    as scoring (`_effective_duty_day_rows`), so Σ contribution scores equals
    the duty part of that quarter's soldier_score up to projection
    quantization (<1e-6 per bucket)."""
    if not quarters:
        return {}

    from sqlalchemy import select

    from app.db.models import DutyType, ScoreAdjustment
    from app.services.scoring import _duty_type_scores, _effective_duty_day_rows

    dt_scores = _duty_type_scores(session)
    dt_names = {
        dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()
    }
    lo = min(quarters)
    hi = quarter_end(max(quarters))
    grouped: dict[date, dict[tuple[uuid.UUID, str], dict[str, Any]]] = {}
    for row in _effective_duty_day_rows(session, statuses=["published"], date_from=lo, date_to=hi):
        if row["effective_soldier_id"] != soldier_id:
            continue
        qs = quarter_start(row["day"])
        if qs not in quarters:
            continue
        key = (row["assignment_id"], row["multiplier_source"], row["duty_type_id"])
        bucket = grouped.setdefault(qs, {}).setdefault(
            key,
            {"days": 0, "weighted_total": Decimal("0"), "start": row["day"], "end": row["day"]},
        )
        bucket["days"] += 1
        bucket["weighted_total"] += row["weighted_multiplier"]
        bucket["end"] = row["day"]

    out: dict[date, list[BurdenShareContribution]] = {qs: [] for qs in quarters}
    for qs, buckets in grouped.items():
        for (_assignment_id, source, duty_type_id), b in sorted(
            buckets.items(), key=lambda kv: kv[1]["start"]
        ):
            score = dt_scores.get(duty_type_id, Decimal("0")) * b["weighted_total"]
            out[qs].append(BurdenShareContribution(
                kind="duty",
                label=dt_names.get(duty_type_id) or "סוג תורנות שנמחק",
                score=score,
                detail=_MULTIPLIER_SOURCE_LABELS.get(source, ""),
                start_date=b["start"],
                end_date=b["end"],
                days=b["days"],
                multiplier=(b["weighted_total"] / Decimal(b["days"])).quantize(Decimal("0.001")),
            ))

    adj_rows = session.execute(
        select(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier_id)
    ).scalars().all()
    for adj in adj_rows:
        qs = quarter_start(adj.created_at.date())
        if qs not in quarters:
            continue
        out[qs].append(BurdenShareContribution(
            kind="adjustment",
            label=adj.reason or "התאמת ניקוד ידנית",
            score=Decimal(adj.delta),
        ))
    return out


@dataclass
class BurdenShareBreakdown:
    """Full per-quarter breakdown for one soldier, plus the aggregate result."""
    quarters: list[BurdenShareQuarterDetail] = field(default_factory=list)
    burden_share: Decimal = Decimal("0")
    # Raw components: burden_share = A_i / W_i
    A_i: Decimal = Decimal("0")   # Σ(s_q × active_frac_q)  — personal weighted score
    W_i: Decimal = Decimal("0")   # Σ(U_q × active_frac_q)  — unit weighted score


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
    effective_duty_days uses for published assignments. Keyed by the UNCLIPPED
    calendar quarter_start. Used by compute_effort_data's pending_duties parameter
    to inflate a quarter's unit_score denominator by the workload the algorithm is
    about to assign this run, assuming full coverage.
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
    soldiers: list[Any],   # objects with .id (UUID), .enrolled_at (date), .unit_join_date (date | None)
    quarters: list[tuple[date, date]],
    quarter_unit_scores: dict[date, Decimal],   # keyed by quarter_start date
    quarter_soldier_scores: dict[date, dict[uuid.UUID, Decimal]],  # keyed by quarter_start date
    soldier_reset_dates: dict[uuid.UUID, date],
) -> dict[uuid.UUID, EffortData]:
    """
    Pure-logic core: compute EffortData per soldier given pre-aggregated quarter scores.

    effort_score = A_i / W_i  where:
        A_i = Σ(s_q × active_frac_q)   — personal weighted score
        W_i = Σ(U_q × active_frac_q)   — unit total weighted score

    This is scale-invariant across quarters: a quarter with 10× more total work
    contributes proportionally more to the denominator, so it can never permanently
    inflate a soldier's effort relative to a later quarter.  Equal effort for all
    soldiers requires equal share (s_q/U_q) in every quarter — and this formula
    converges toward that: as future quarters accumulate work, a soldier's overloaded
    historical share dilutes naturally without needing retroactive reassignment.

    Both active_in_q (numerator) and q_days (denominator) clip to the SAME
    per-soldier floor: max(quarter_start, this soldier's own resolved reset
    date). Clipping only the numerator (the historical bug this replaces)
    understates active_frac for any soldier whose own reset date is later
    than whichever date the shared `quarters` list happened to be built
    from — which now happens routinely once reset dates vary per hierarchy
    node instead of being one global value for the whole run.

    C_over_D = 1 / (max(W_i, 1) × 1000)
        Used by the bridge as: effort_per_milli = int(C_over_D × EFFORT_SCALE)
        (no unit_score_milli division — the score units cancel differently now).
    """
    result: dict[uuid.UUID, EffortData] = {}

    for soldier in soldiers:
        A_i = Decimal("0")  # Σ(s_q × active_frac_q)
        W_i = Decimal("0")  # Σ(U_q × active_frac_q)
        own_reset = soldier_reset_dates[soldier.id]
        activation = soldier.unit_join_date or soldier.enrolled_at

        for q_start, q_end in quarters:
            own_floor = max(q_start, own_reset)
            if own_floor > q_end:
                continue  # this quarter is entirely before the soldier's own reset date
            q_days = (q_end - own_floor).days + 1

            soldier_start = max(own_floor, activation)
            if soldier_start > q_end:
                continue  # soldier not enrolled in this quarter

            active_in_q = (q_end - soldier_start).days + 1
            active_frac = Decimal(active_in_q) / Decimal(q_days)

            unit_score = quarter_unit_scores.get(q_start, Decimal("0"))
            if unit_score > 0:
                s_score = quarter_soldier_scores.get(q_start, {}).get(soldier.id, Decimal("0"))
                A_i += s_score * active_frac
                W_i += unit_score * active_frac

        effective_W = W_i if W_i > Decimal("0") else Decimal("1")
        effort_score = A_i / W_i if W_i > Decimal("0") else Decimal("0")
        C_over_D = Decimal("1") / (effective_W * 1000)
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
    published). Each one's score is added to whichever quarter(s) it falls in as a
    denominator-only contribution — nobody is credited yet. This stops a thin quarter
    from making one pre-existing duty look like a huge personal share.

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

    # Merge the about-to-be-assigned workload into whichever quarter(s) it falls in,
    # creating a new unclipped quarter tuple if none is tracked yet. Computed before
    # the "anything to do" check so pending-only duties can be the sole reason a
    # quarter exists.
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
            soldier_reset_dates={s.id: reset_date for s in soldiers},
        )

    # Fetch duty type scores
    dt_scores: dict[uuid.UUID, Decimal] = {
        dt.id: dt.score_per_day
        for dt in session.execute(select(DutyType)).scalars().all()
    }

    # Map calendar-quarter-start → clipped quarter-start used in all_quarters.
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
        soldier_reset_dates={s.id: reset_date for s in soldiers},
    )


def compute_burden_share_breakdown(
    session: Session,
    *,
    soldier: Any,   # object with .id (UUID) and .enrolled_at (date)
    planning_start: date,
    planning_end: date,
    reset_date: date,
    extra_adj_delta: Decimal = Decimal("0"),
    extra_adj_date: date | None = None,
) -> BurdenShareBreakdown:
    """
    Compute a full per-quarter burden-share breakdown for a single soldier.

    Includes manual score adjustments (ScoreAdjustment records) in the calculation.
    Pass extra_adj_delta + extra_adj_date to simulate a hypothetical future adjustment
    (used by the preview endpoint).

    Returns BurdenShareBreakdown with one BurdenShareQuarterDetail per historical quarter
    (past and future beyond planning window) plus the aggregate burden_share and C_over_D.
    """
    from app.services.scoring import _try_projected_burden_share_breakdown

    projected = _try_projected_burden_share_breakdown(
        session,
        soldier=soldier,
        planning_start=planning_start,
        planning_end=planning_end,
        reset_date=reset_date,
        extra_adj_delta=extra_adj_delta,
        extra_adj_date=extra_adj_date,
    )
    if projected is not None:
        return projected

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
    # breakdown's quarters and burden_share match the algorithm's exactly.
    days_data = effective_duty_days(session, date_from=reset_date, date_to=date(2099, 12, 31))
    future_quarters = _build_future_quarters(days_data, planning_end)
    quarters = past_quarters + future_quarters

    if not quarters:
        return BurdenShareBreakdown(quarters=[], burden_share=Decimal("0"), A_i=Decimal("0"), W_i=Decimal("0"))

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
    quarter_details: list[BurdenShareQuarterDetail] = []
    A_i = Decimal("0")  # Σ(s_q × active_frac_q)
    W_i = Decimal("0")  # Σ(U_q × active_frac_q)

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
            A_i += s_score * active_frac
            W_i += unit_score * active_frac

        true_q_end = quarter_end(q_start_d)
        quarter_details.append(BurdenShareQuarterDetail(
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

    burden_share = A_i / W_i if W_i > Decimal("0") else Decimal("0")

    if quarter_details:
        contrib_map = compute_quarter_contributions(
            session,
            soldier_id=soldier.id,
            quarters={quarter_start(d.quarter_start) for d in quarter_details},
        )
        for d in quarter_details:
            d.contributions = contrib_map.get(quarter_start(d.quarter_start), [])

    return BurdenShareBreakdown(
        quarters=quarter_details,
        burden_share=burden_share,
        A_i=A_i,
        W_i=W_i,
    )
