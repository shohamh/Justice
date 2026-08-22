from __future__ import annotations

import dataclasses
import json
import math
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.algorithm.availability import analyze_duty_availability
from app.algorithm.duration import score_days
from app.algorithm.types import (
    AssignmentExplanation as AlgoExplanation,
)
from app.algorithm.types import (
    BatchShiftFill,
    DutyBlock,
    ExistingAssignment,
    ExplanationData,
    SoldierInput,
    SolverResult,
    SolverSettings,
)
from app.audit.writer import write_audit
from app.db.models import (
    AlgorithmJob,
    AssignmentExplanation,
    DutyAssignment,
    DutyReserveLink,
    DutyShift,
    DutyShiftNodeQuota,
    DutyType,
    ExemptionDutyLocationMap,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
    SoldierExemption,
)
from app.services import scoring as scoring_svc
from app.services.effort_score import EFFORT_SCALE, EffortData, compute_effort_data, quarter_start
from app.services.rest import effective_assignment_end, resolve_rest_hours
from app.services.settings_loader import get_setting_int

_cancel_events: dict[str, threading.Event] = {}


def _watch_job_timeout(job_id: uuid.UUID, cancel_event: threading.Event, max_seconds: float) -> None:
    """Daemon thread: force-cancels a job still running after max_seconds.

    Nothing in the solve path enforces an overall wall-clock budget — each batch's
    relaxation ladder can legitimately spend its full time_limit_seconds per rung
    with no upper bound on total batches × rungs. Without this, a run that hits that
    worst case is indistinguishable from a true hang and never reaches a terminal
    status. Mirrors cancel_job's DB update (status/error_message/finished_at) so a
    timed-out job looks the same to the UI as a manual cancel, just with a distinct
    error_message.
    """
    from app.db.session import session_scope

    if cancel_event.wait(timeout=max_seconds):
        return  # finished normally, or cancelled by the user, before the deadline
    with session_scope() as session:
        job = session.get(AlgorithmJob, job_id)
        if job is not None and job.status == "running":
            job.status = "failed"
            job.error_message = json.dumps({"status": "INTERRUPTED", "reason": "timed_out"})
            job.finished_at = datetime.now(tz=UTC)
            session.commit()
    cancel_event.set()


def _count_space_stats(
    soldiers: list[SoldierInput],
    assignments: list,
    duties: list[DutyBlock],
    effort_resolution: int = 1_000,
    effort_range_min: int = 0,
    effort_range_max: int = 0,
) -> dict[str, Any]:
    """Compute count-space effort CV for the whole soldier pool."""
    from app.algorithm.model import _block_score
    range_size = effort_range_max - effort_range_min
    use_range = range_size > 0
    div = max(1, EFFORT_SCALE // effort_resolution)
    duty_map = {d.id: d for d in duties}
    soldier_duties: dict[uuid.UUID, list[DutyBlock]] = {s.id: [] for s in soldiers}
    for a in assignments:
        d = duty_map.get(a.duty_id)
        if d:
            soldier_duties[a.soldier_id].append(d)

    totals: list[float] = []
    for s in soldiers:
        if use_range:
            offset = max(0, min(effort_resolution, (s.effort_offset - effort_range_min) * effort_resolution // range_size))
            weight = sum(
                max(1, s.effort_per_milli * _block_score(d) * effort_resolution // range_size)
                for d in soldier_duties.get(s.id, [])
            )
        else:
            offset = s.effort_offset // div
            weight = sum(
                max(1, (s.effort_per_milli * _block_score(d)) // div)
                for d in soldier_duties.get(s.id, [])
            )
        totals.append(float(offset + weight))

    if not totals:
        return {"cv": None, "mean": None, "stddev": None, "min": None, "max": None, "n": 0}
    mean = sum(totals) / len(totals)
    variance = sum((t - mean) ** 2 for t in totals) / len(totals)
    stddev = math.sqrt(variance)
    cv = stddev / mean if mean > 0 else 0.0
    return {
        "cv": round(cv, 4),
        "mean": round(mean, 2),
        "stddev": round(stddev, 2),
        "min": round(min(totals), 2),
        "max": round(max(totals), 2),
        "n": len(totals),
    }


def exempted_duty_type_ids_by_soldier(
    session: Session, *, as_of: date
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Per-soldier duty-type ids the soldier is exempt from at `as_of`.

    Resolves the same union as ``SoldierInput.exempted_duty_type_ids`` in
    :func:`load_soldier_inputs` — exemption mappings plus eligibility
    exclusions — without loading any duty-day scores. Callers that only need
    exemption scope (e.g. fairness grouping) avoid the full canonical scoring
    expansion this way.
    """
    etid_to_dtids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        etid_to_dtids.setdefault(etid, set()).add(dtid)

    global_etids: set[uuid.UUID] = set(
        session.execute(
            select(ExemptionType.id).where(ExemptionType.is_global.is_(True))
        ).scalars().all()
    )
    active_dt_ids: set[uuid.UUID] = set(
        session.execute(select(DutyType.id).where(DutyType.active.is_(True))).scalars().all()
    )
    full_coverage_etids: set[uuid.UUID] = set(global_etids)
    if active_dt_ids:
        full_coverage_etids.update(
            etid for etid, dts in etid_to_dtids.items() if active_dt_ids <= dts
        )
        for etid in global_etids:
            etid_to_dtids[etid] = active_dt_ids

    result: dict[uuid.UUID, set[uuid.UUID]] = {}
    for ex in session.execute(select(SoldierExemption)).scalars().all():
        if ex.start_date <= as_of and (ex.end_date is None or ex.end_date >= as_of):
            result.setdefault(ex.soldier_id, set()).update(
                etid_to_dtids.get(ex.exemption_type_id, set())
            )

    from app.services.eligibility import compute_eligibility_exclusions
    from app.services.settings_loader import get_setting

    def _setting_int(key: str, default: int) -> int:
        try:
            return int(get_setting(session, key))
        except Exception:
            return default

    soldiers = (
        session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    )
    eligibility_exclusions = compute_eligibility_exclusions(
        session,
        soldiers,
        mitvahim_months=_setting_int("eligibility.mitvahim_months", 6),
        alal_months=_setting_int("eligibility.alal_months", 3),
        reference_date=as_of,
    )
    for soldier_id, dtids in eligibility_exclusions.items():
        result.setdefault(soldier_id, set()).update(dtids)
    return result


def load_soldier_inputs(
    session: Session, *, as_of: date, eligible_node_ids: list[uuid.UUID] | None = None
) -> list[SoldierInput]:
    """Load every active soldier as a SoldierInput for the algorithm."""
    soldiers = (
        session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    )
    node_path_map: dict[uuid.UUID, list[uuid.UUID]] = {
        n.id: list(n.path_ids)
        for n in session.execute(select(HierarchyNode.id, HierarchyNode.path_ids)).all()
    }
    if eligible_node_ids:
        eligible_set = {uuid.UUID(str(nid)) for nid in eligible_node_ids}
        soldiers = [
            s for s in soldiers
            if s.hierarchy_node_id is not None
            and eligible_set & set(node_path_map.get(s.hierarchy_node_id, []))
        ]
    duty_scores = scoring_svc.duty_score_by_soldier(session)
    adj_scores = scoring_svc.adjustments_by_soldier(session)

    # Include algorithm_draft scores so repeated runs deprioritise already-assigned soldiers.
    # Draft assignments are proposals that haven't been published yet; counting them prevents
    # the solver from piling duties on the same person across consecutive runs.
    draft_scores: dict[uuid.UUID, Decimal] = {}
    dt_score_map = {
        dt.id: dt.score_per_day
        for dt in session.execute(select(DutyType)).scalars().all()
    }
    for da in session.execute(
        select(DutyAssignment).where(DutyAssignment.status == "algorithm_draft")
    ).scalars().all():
        days = (da.end_date - da.start_date).days
        draft_scores[da.soldier_id] = (
            draft_scores.get(da.soldier_id, Decimal("0"))
            + dt_score_map.get(da.duty_type_id, Decimal("0")) * days
        )

    # Build exemption type → duty type ids map (one query)
    etid_to_dtids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        etid_to_dtids.setdefault(etid, set()).add(dtid)

    # Build exemption type → duty location ids map (one query)
    etid_to_locids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for etid, locid in session.execute(
        select(ExemptionDutyLocationMap.exemption_type_id, ExemptionDutyLocationMap.duty_location_id)
    ).all():
        etid_to_locids.setdefault(etid, set()).add(locid)

    # Global exemption types (is_global=True) cover ALL active duty types
    global_etids: set[uuid.UUID] = set(
        session.execute(
            select(ExemptionType.id).where(ExemptionType.is_global.is_(True))
        ).scalars().all()
    )

    # Determine which exemption types provide full coverage (cover ALL active duty types)
    active_dt_ids: set[uuid.UUID] = set(
        session.execute(select(DutyType.id).where(DutyType.active.is_(True))).scalars().all()
    )
    full_coverage_etids: set[uuid.UUID] = set(global_etids)
    if active_dt_ids:
        full_coverage_etids.update(
            etid for etid, dts in etid_to_dtids.items() if active_dt_ids <= dts
        )
        # Add global exemption types to the map with all active duty types
        for etid in global_etids:
            etid_to_dtids[etid] = active_dt_ids

    # All exemptions touching [enrolled_at, as_of] — one bulk query for all soldiers
    all_exemptions = session.execute(select(SoldierExemption)).scalars().all()

    # Per-soldier: duty-type exemptions and full-coverage exempt date sets
    soldier_exempt_dtype_ids: dict[uuid.UUID, set[uuid.UUID]] = {}
    soldier_exempt_locids: dict[uuid.UUID, set[uuid.UUID]] = {}
    soldier_full_exempt_dates: dict[uuid.UUID, set[date]] = {}

    for ex in all_exemptions:
        # Active exemption check for duty-type resolution (as_of)
        if ex.start_date <= as_of and (ex.end_date is None or ex.end_date >= as_of):
            dtids = etid_to_dtids.get(ex.exemption_type_id, set())
            soldier_exempt_dtype_ids.setdefault(ex.soldier_id, set()).update(dtids)
            soldier_exempt_locids.setdefault(ex.soldier_id, set()).update(
                etid_to_locids.get(ex.exemption_type_id, set())
            )

        # Full-coverage exempt dates (for active_days calculation)
        if ex.exemption_type_id in full_coverage_etids:
            s_dates = soldier_full_exempt_dates.setdefault(ex.soldier_id, set())
            d = ex.start_date
            hi = ex.end_date if ex.end_date is not None else as_of
            while d <= hi:
                s_dates.add(d)
                d += timedelta(days=1)

    from app.services.eligibility import compute_eligibility_exclusions
    from app.services.settings_loader import get_setting

    def _setting_int(key: str, default: int) -> int:
        try:
            return int(get_setting(session, key))
        except Exception:
            return default

    mitvahim_months = _setting_int("eligibility.mitvahim_months", 6)
    alal_months = _setting_int("eligibility.alal_months", 3)

    eligibility_exclusions = compute_eligibility_exclusions(
        session, soldiers, mitvahim_months=mitvahim_months, alal_months=alal_months, reference_date=as_of
    )

    # Approved personal constraints per soldier (one query)
    constraints = (
        session.execute(
            select(PersonalConstraint).where(PersonalConstraint.status == "approved")
        )
        .scalars()
        .all()
    )
    soldier_constraints: dict[uuid.UUID, list[tuple[date, date]]] = {}
    for c in constraints:
        soldier_constraints.setdefault(c.soldier_id, []).append((c.start_date, c.end_date))

    result: list[SoldierInput] = []
    for s in soldiers:
        cum = (
            duty_scores.get(s.id, Decimal("0"))
            + adj_scores.get(s.id, Decimal("0"))
            + draft_scores.get(s.id, Decimal("0"))
        )

        # Compute active_days inline (avoids 2N extra queries)
        raw = (as_of - s.enrolled_at).days
        raw = max(1, raw)
        exempt_days = len(soldier_full_exempt_dates.get(s.id, set()))
        ad = max(1, raw - exempt_days)

        combined_exempt = soldier_exempt_dtype_ids.get(s.id, set()) | eligibility_exclusions.get(s.id, set())
        result.append(
            SoldierInput(
                id=s.id,
                enrolled_at=s.enrolled_at,
                cumulative_score=cum,
                active_days=ad,
                hierarchy_node_id=s.hierarchy_node_id,
                path_ids=node_path_map.get(s.hierarchy_node_id, []) if s.hierarchy_node_id else [],
                approved_constraint_dates=soldier_constraints.get(s.id, []),
                exempted_duty_type_ids=combined_exempt,
                exempted_duty_location_ids=soldier_exempt_locids.get(s.id, set()),
            )
        )
    return result


def load_duty_blocks(
    session: Session,
    *,
    planning_start: date,
    planning_end: date,
    duty_type_ids: list[uuid.UUID],
    duty_location_id: uuid.UUID,
) -> list[DutyBlock]:
    """Synthesise one DutyBlock per (duty_type, day) in the planning window."""
    types = (
        session.execute(
            select(DutyType).where(DutyType.id.in_(duty_type_ids), DutyType.active.is_(True))
        )
        .scalars()
        .all()
    )
    blocks: list[DutyBlock] = []
    requirements_map = {dt.id: dt.requirements or {} for dt in types}
    day = planning_start
    while day <= planning_end:
        for dt in types:
            blocks.append(
                DutyBlock(
                    id=uuid.uuid4(),
                    duty_type_id=dt.id,
                    duty_location_id=duty_location_id,
                    start_date=day,
                    end_date=day,
                    score_per_day=dt.score_per_day,
                    required_range_type=dt.required_range_type,
                    requirements=requirements_map.get(dt.id, {}),
                )
            )
        day += timedelta(days=1)
    return blocks


def reserve_count_for_shift(session: Session, *, shift: DutyShift) -> int:
    """Effective reserve count: override if set, else max(minimum, ceil(ratio × required_count))."""
    if shift.reserve_count_override is not None:
        return shift.reserve_count_override
    dt = session.get(DutyType, shift.duty_type_id)
    if dt is None:
        return 0
    ratio = float(dt.reserve_ratio or 0)
    minimum = int(dt.reserve_minimum or 0)
    calculated = math.ceil(shift.required_count * ratio)
    return max(minimum, calculated)


def load_duty_blocks_from_shifts(
    session: Session,
    *,
    shift_ids: list[uuid.UUID],
    standby_multiplier: Decimal = Decimal("0.2"),
) -> tuple[list[DutyBlock], dict[uuid.UUID, uuid.UUID]]:
    """Expand DutyShift rows into primary + reserve DutyBlocks.

    Returns (all_blocks, block_to_shift_map). Reserve blocks have
    is_reserve=True and score_per_day scaled by standby_multiplier.
    """
    shifts = session.execute(
        select(DutyShift).where(DutyShift.id.in_(shift_ids), DutyShift.status == "active")
    ).scalars().all()

    type_ids = {s.duty_type_id for s in shifts}
    types_q = session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars().all()
    score_map = {dt.id: dt.score_per_day for dt in types_q}
    required_range_type_map = {dt.id: dt.required_range_type for dt in types_q}
    requirements_map = {dt.id: dt.requirements or {} for dt in types_q}
    default_rest_hours = get_setting_int(session, "duty.default_rest_hours", 12)
    rest_hours_map = {dt.id: resolve_rest_hours(dt, default_rest_hours) for dt in types_q}

    # Batch-load per-shift node quotas, then expand each shift's quota dict
    # ({node_id: count}) into a flat list of singleton {node_id: 1} dicts — one per
    # quota'd slot. These are assigned, in order, to that shift's PRIMARY DutyBlocks
    # only (reserve/standby slots are not subject to node quotas). Any primary slots
    # beyond the expanded quota list (e.g. quotas summing to less than required_count)
    # get node_quotas=None, i.e. unconstrained.
    quota_rows = session.execute(
        select(DutyShiftNodeQuota).where(DutyShiftNodeQuota.duty_shift_id.in_(shift_ids))
    ).scalars().all()
    quotas_by_shift: dict[uuid.UUID, list[tuple[uuid.UUID, int]]] = {}
    for q in quota_rows:
        quotas_by_shift.setdefault(q.duty_shift_id, []).append((q.hierarchy_node_id, q.count))

    blocks: list[DutyBlock] = []
    block_to_shift: dict[uuid.UUID, uuid.UUID] = {}
    today = date.today()

    for shift in shifts:
        effective_start = max(shift.start_date, today)
        if effective_start >= shift.end_date:
            # Shift is entirely in the past — nothing left to assign
            continue
        block_start_time = shift.start_time if effective_start == shift.start_date else "00:00"
        # Only generate blocks for UNFILLED slots. Subtract assignments that already
        # occupy this shift (published or pending draft) so re-running a fully-assigned
        # schedule is a no-op instead of regenerating slots and competing against its own
        # published assignments (which saturates the soldiers and yields ~0 new coverage).
        counts = session.execute(
            select(
                func.count(DutyAssignment.id).label("total"),
                func.coalesce(
                    func.sum(case((DutyAssignment.is_reserve.is_(True), 1), else_=0)), 0
                ).label("reserve"),
            ).where(
                DutyAssignment.duty_shift_id == shift.id,
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        ).one()
        filled_total = counts.total or 0
        filled_reserve = counts.reserve or 0
        filled_primary = filled_total - filled_reserve

        score = score_map.get(shift.duty_type_id, Decimal("1.00"))
        primary_needed = max(0, shift.required_count - filled_primary)
        expanded_quotas: list[dict[uuid.UUID, int]] = [
            {node_id: 1}
            for node_id, count in quotas_by_shift.get(shift.id, [])
            for _ in range(count)
        ]
        for i in range(primary_needed):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=effective_start,
                end_date=shift.end_date,
                start_time=block_start_time,
                end_time=shift.end_time,
                score_per_day=score,
                is_reserve=False,
                eligible_node_ids=shift.eligible_node_ids,
                node_quotas=expanded_quotas[i] if i < len(expanded_quotas) else None,
                rest_hours=rest_hours_map.get(shift.duty_type_id, default_rest_hours),
                required_range_type=required_range_type_map.get(shift.duty_type_id),
                requirements=requirements_map.get(shift.duty_type_id, {}),
            ))
            block_to_shift[block_id] = shift.id
        r_count = reserve_count_for_shift(session, shift=shift)
        reserve_needed = max(0, r_count - filled_reserve)
        r_score = score * standby_multiplier
        for _ in range(reserve_needed):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=effective_start,
                end_date=shift.end_date,
                start_time=block_start_time,
                end_time=shift.end_time,
                score_per_day=r_score,
                is_reserve=True,
                eligible_node_ids=shift.eligible_node_ids,
                rest_hours=rest_hours_map.get(shift.duty_type_id, default_rest_hours),
                required_range_type=required_range_type_map.get(shift.duty_type_id),
                requirements=requirements_map.get(shift.duty_type_id, {}),
            ))
            block_to_shift[block_id] = shift.id

    return blocks, block_to_shift


def inject_effort_scores(
    soldiers: list[SoldierInput],
    duty_blocks: list[DutyBlock],
    effort_map: dict[uuid.UUID, EffortData],
) -> tuple[int, int]:
    """Set effort_offset and effort_per_milli on each SoldierInput in-place.

    effort_per_milli = int(C_over_D × EFFORT_SCALE)
    where C_over_D = 1 / (Σ(U_q × active_frac_q) × 1000).
    Each milli-point of score assigned to a soldier increases their effort by
    C_over_D × EFFORT_SCALE in solver-scale units (≈ score_pts / W_global).

    unit_score_milli is still computed to guard against empty windows and to
    bound the worst-case effort accumulation for range encoding.

    Returns (effort_range_min, effort_range_max) — tight bounds covering every possible
    effort_offset value throughout the entire run (including worst-case accumulation).
    """
    unit_score_milli = sum(
        int(float(b.score_per_day) * score_days(b.start_date, b.end_date, b.start_time, b.end_time) * 1000)
        for b in duty_blocks
    )
    for s in soldiers:
        data = effort_map.get(s.id)
        if data is None:
            continue
        s.effort_offset = data.effort_offset
        if unit_score_milli > 0:
            s.effort_per_milli = int(float(data.C_over_D) * EFFORT_SCALE)
        else:
            s.effort_per_milli = 0

    # Compute [range_min, range_max] for auto-range count-space encoding.
    # Excludes soldiers with no effort participation (per_milli == 0).
    active = [s for s in soldiers if s.effort_per_milli > 0]
    if not active:
        return (0, EFFORT_SCALE)

    range_min = min(s.effort_offset for s in active)
    # Worst case: highest-per_milli soldier is assigned every single duty in this run.
    max_accumulation = max(s.effort_per_milli for s in active) * unit_score_milli
    range_max = max(s.effort_offset for s in active) + max_accumulation
    # Ensure range is always strictly positive so division is safe.
    if range_max <= range_min:
        range_max = range_min + max(1, max_accumulation)
    return (range_min, range_max)


def effort_history_horizon(session: Session, *, planning_start: date) -> date:
    """Return the exclusive upper bound for the effort-history window.

    Effort must reflect ALL published commitments, including assignments already
    published for dates AFTER this planning window (schedules are routinely
    published months ahead).  We therefore extend the window to the day after
    the latest published assignment, so a soldier who is already booked far into
    the future shows the corresponding effort and is deprioritised for new
    duties.  The unpublished duties of the current run are never published yet,
    so they are excluded automatically.

    Falls back to ``planning_start`` when there is no published work at/after it
    (the historical case where published == past).
    """
    latest_published_end = session.execute(
        select(func.max(DutyAssignment.end_date)).where(
            DutyAssignment.status == "published"
        )
    ).scalar()
    if latest_published_end is not None and latest_published_end >= planning_start:
        return latest_published_end + timedelta(days=1)
    return planning_start


def load_existing_assignments(
    session: Session,
    *,
    planning_start: date,
    planning_end: date,
    W: int,
) -> list[ExistingAssignment]:
    """Load published assignments within W days of the planning window for spacing checks."""
    boundary_start = planning_start - timedelta(days=W)
    boundary_end = planning_end + timedelta(days=W)
    rows = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.start_date <= boundary_end,
                DutyAssignment.end_date >= boundary_start,
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []

    type_ids = {a.duty_type_id for a in rows}
    types_q = session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars().all()
    default_rest_hours = get_setting_int(session, "duty.default_rest_hours", 12)
    rest_hours_map = {dt.id: resolve_rest_hours(dt, default_rest_hours) for dt in types_q}

    result: list[ExistingAssignment] = []
    for a in rows:
        end_dt = effective_assignment_end(session, a)
        result.append(
            ExistingAssignment(
                soldier_id=a.soldier_id,
                duty_type_id=a.duty_type_id,
                start_date=a.start_date,
                end_date=a.end_date,
                is_reserve=a.is_reserve,
                rest_hours=rest_hours_map.get(a.duty_type_id, default_rest_hours),
                rest_effective_end_date=end_dt.date(),
                rest_effective_end_time=end_dt.strftime("%H:%M"),
            )
        )
    return result


def populate_eligibility_data(
    session: Session,
    *,
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    settings: SolverSettings,
) -> None:
    """Populate the same hard-eligibility facts used by solving and preflight."""
    if settings.enforce_weapon_qualification:
        from app.services.weapon_eligibility import bulk_ineligible_duty_blocks

        weapon_ineligible = bulk_ineligible_duty_blocks(
            session,
            soldier_ids=[s.id for s in soldiers],
            duties=duties,
            respect_system_toggle=False,
            include_alal=False,
        )
        for soldier in soldiers:
            soldier.weapon_ineligible_duty_block_ids = weapon_ineligible.get(soldier.id, set())

    from app.services.rank_eligibility_projection import bulk_future_ineligible_duty_blocks

    future_ineligible = bulk_future_ineligible_duty_blocks(
        session, soldier_ids=[s.id for s in soldiers], duties=duties,
    )
    for soldier in soldiers:
        soldier.future_ineligible_duty_block_ids = future_ineligible.get(soldier.id, set())


def analyze_shift_availability(
    session: Session,
    *,
    shift_ids: list[uuid.UUID],
    settings_json: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return pre-run candidate availability for selected unfilled shifts."""
    duties, block_to_shift = load_duty_blocks_from_shifts(session, shift_ids=shift_ids)
    if not duties:
        return []
    settings = resolve_solver_settings(session, settings_json)
    planning_start = min(duty.start_date for duty in duties)
    planning_end = max(duty.end_date for duty in duties)
    soldiers = load_soldier_inputs(
        session,
        as_of=planning_start,
        eligible_node_ids=settings_json.get("eligible_node_ids"),
    )
    populate_eligibility_data(session, soldiers=soldiers, duties=duties, settings=settings)
    existing = load_existing_assignments(
        session, planning_start=planning_start, planning_end=planning_end, W=settings.Wr,
    )
    duty_types = {
        dt.id: dt.name
        for dt in session.execute(
            select(DutyType).where(DutyType.id.in_({d.duty_type_id for d in duties}))
        ).scalars()
    }
    grouped: dict[uuid.UUID, list[DutyBlock]] = {}
    for duty in duties:
        grouped.setdefault(block_to_shift[duty.id], []).append(duty)

    result: list[dict[str, Any]] = []
    for shift_id, shift_duties in grouped.items():
        per_block = [
            analyze_duty_availability(
                soldiers,
                duty,
                existing=existing,
                enforce_weapon_qualification=settings.enforce_weapon_qualification,
            )
            for duty in shift_duties
        ]
        representative = shift_duties[0]
        blocker_counts = {
            key: max(availability.blocker_counts.get(key, 0) for availability in per_block)
            for key in {
                key
                for availability in per_block
                for key in availability.blocker_counts
            }
        }
        eligible_count = max(availability.eligible_count for availability in per_block)
        available_count = max(availability.available_count for availability in per_block)
        required_count = len(shift_duties)
        result.append({
            "shift_id": str(shift_id),
            "duty_type_id": str(representative.duty_type_id),
            "duty_type_name": duty_types.get(representative.duty_type_id, ""),
            "start_date": representative.start_date.isoformat(),
            "end_date": representative.end_date.isoformat(),
            "required_count": required_count,
            "eligible_count": eligible_count,
            "available_count": available_count,
            "shortfall": max(0, required_count - available_count),
            "blocker_counts": blocker_counts,
        })
    return result


def build_hierarchy_maps(
    session: Session,
) -> tuple[
    dict[uuid.UUID, uuid.UUID | None],
    dict[uuid.UUID, list[uuid.UUID]],
    dict[uuid.UUID, uuid.UUID],
    dict[uuid.UUID, list[uuid.UUID]],
]:
    """Return (hierarchy_parent, hierarchy_children, soldier_node, node_soldiers)."""
    nodes = session.execute(select(HierarchyNode)).scalars().all()
    soldiers = (
        session.execute(
            select(Soldier.id, Soldier.hierarchy_node_id).where(Soldier.left_at.is_(None))
        )
        .all()
    )

    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None] = {n.id: n.parent_id for n in nodes}
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]] = {n.id: [] for n in nodes}
    for n in nodes:
        if n.parent_id is not None and n.parent_id in hierarchy_children:
            hierarchy_children[n.parent_id].append(n.id)

    soldier_node: dict[uuid.UUID, uuid.UUID] = {}
    node_soldiers: dict[uuid.UUID, list[uuid.UUID]] = {n.id: [] for n in nodes}
    for sid, nid in soldiers:
        if nid is not None:
            soldier_node[sid] = nid
            node_soldiers.setdefault(nid, []).append(sid)

    return hierarchy_parent, hierarchy_children, soldier_node, node_soldiers


def _build_node_parents(
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
) -> dict[uuid.UUID, uuid.UUID]:
    """Maps every hierarchy node id to its immediate parent id, for the
    solver's one-level-up quota relaxation (see app.algorithm.solver).

    Root nodes (parent_id is None) are omitted since there's no parent to
    relax onto.
    """
    return {node_id: parent_id for node_id, parent_id in hierarchy_parent.items() if parent_id is not None}


def _explanation_payload(
    exp: AlgoExplanation,
    *,
    dm_view: bool,
    soldier_names: dict[uuid.UUID, str],
) -> dict[str, Any]:
    """Serialise one AssignmentExplanation to a JSON-safe dict.

    Pre-computes pool_size/blocked_count/assigned_rank from the full candidate
    list, then truncates to top-10 unblocked + 5 blocked before storing.
    Keeps JSONB payloads small (~1-2KB instead of ~40KB) while preserving the
    aggregate stats the UI needs.
    """
    assigned_id = exp.assigned_soldier_id

    unblocked = [c for c in exp.candidates if not c.blocked]
    blocked_list = [c for c in exp.candidates if c.blocked]

    pool_size = len(unblocked)
    blocked_count = len(blocked_list)

    unblocked_sorted = sorted(
        unblocked,
        key=lambda c: c.pre_effort_score if c.pre_effort_score is not None else float("inf"),
    )
    assigned_rank = next(
        (i + 1 for i, c in enumerate(unblocked_sorted) if c.soldier_id == assigned_id),
        None,
    )

    # Top 10 unblocked for display; always include the assigned soldier even if rank > 10
    display_unblocked: list = unblocked_sorted[:10]
    if assigned_rank is not None and assigned_rank > 10:
        assigned_c = next(c for c in unblocked_sorted if c.soldier_id == assigned_id)
        display_unblocked = display_unblocked + [assigned_c]

    display_candidates = display_unblocked + blocked_list[:5]

    candidates = []
    for c in display_candidates:
        entry: dict[str, Any] = {
            "soldier_id": str(c.soldier_id),
            "blocked": c.blocked,
            "blocking_constraints": c.blocking_constraints,
        }
        if dm_view:
            entry["soldier_name"] = soldier_names.get(c.soldier_id, "")
            entry["pre_norm_score"] = c.pre_effort_score
            entry["post_norm_score"] = c.post_effort_score
        candidates.append(entry)

    return {
        "duty_id": str(exp.duty_id),
        "assigned_soldier_id": str(assigned_id),
        "tiebreaker_note": exp.tiebreaker_note,
        "pool_size": pool_size,
        "blocked_count": blocked_count,
        "assigned_rank": assigned_rank,
        "candidates": candidates,
    }


def persist_results(
    session: Session,
    *,
    job: AlgorithmJob,
    result: SolverResult,
    explanation_data: ExplanationData,
    duty_blocks: list,
    soldier_names: dict[uuid.UUID, str],
    actor_id: uuid.UUID | None,
    block_to_shift_map: dict[uuid.UUID, uuid.UUID] | None = None,
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None] | None = None,
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]] | None = None,
    soldier_node: dict[uuid.UUID, uuid.UUID] | None = None,
    duty_to_batch: dict[uuid.UUID, int] | None = None,
) -> None:
    """Insert algorithm_draft assignments, explanations (primary only), and reserve links."""
    import logging as _logging
    import time as _time_pr
    _pr_log = _logging.getLogger(__name__)
    _pr_t0 = _time_pr.monotonic()

    def _pr_phase(label: str) -> None:
        _pr_log.info("[persist_results] phase=%-35s elapsed=%.1fs", label, _time_pr.monotonic() - _pr_t0)

    from app.algorithm.reserve import link_reserves

    duty_map = {d.id: d for d in duty_blocks}
    explanation_map = {e.duty_id: e for e in explanation_data.per_assignment}

    primary_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []
    reserve_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    # Pass 1: insert all DutyAssignment rows and flush so their PKs exist in the DB
    # before we insert AssignmentExplanation rows that FK-reference them.
    created: list[tuple[DutyAssignment, uuid.UUID]] = []  # (da, duty_id)
    for a in result.assignments:
        block: DutyBlock = duty_map[a.duty_id]
        shift_id = block_to_shift_map.get(a.duty_id) if block_to_shift_map else None
        da = DutyAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=block.duty_type_id,
            duty_location_id=block.duty_location_id,
            start_date=block.start_date,
            end_date=block.end_date,
            start_time=block.start_time,
            end_time=block.end_time,
            status="algorithm_draft",
            created_by=actor_id,
            notes=None,
            duty_shift_id=shift_id,
            is_reserve=block.is_reserve,
            algorithm_job_id=job.id,   # NEW
        )
        da.id = uuid.uuid4()
        if duty_to_batch:
            da.batch_index = duty_to_batch.get(a.duty_id)
        session.add(da)
        created.append((da, a.duty_id))

        write_audit(
            session,
            actor_id=actor_id,
            action="algorithm.proposal.create",
            entity_type="duty_assignment",
            entity_id=da.id,
            after={"status": "algorithm_draft", "is_reserve": block.is_reserve},
            context={"job_id": str(job.id)},
        )

        if shift_id:
            if block.is_reserve:
                reserve_assignments.append((da.id, a.soldier_id, shift_id))
            else:
                primary_assignments.append((da.id, a.soldier_id, shift_id))

    _pr_phase(f"pass1 built ({len(created)} rows)")
    # Flush DutyAssignment rows so PKs are committed before FK-child rows
    session.flush()
    _pr_phase("pass1 flush done")

    # Pass 2: insert AssignmentExplanation rows (FK to duty_assignments now safe)
    for da, duty_id in created:
        block: DutyBlock = duty_map[duty_id]
        if not block.is_reserve:
            exp = explanation_map.get(duty_id)
            if exp is not None:
                # Extract scalar fields from the full (pre-truncation) candidate list
                # and store them on the assignment for fast proposal loading.
                assigned_id = exp.assigned_soldier_id
                unblocked = [c for c in exp.candidates if not c.blocked]
                pool_size = len(unblocked)
                unblocked_sorted = sorted(
                    unblocked,
                    key=lambda c: c.pre_effort_score if c.pre_effort_score is not None else float("inf"),
                )
                candidate_rank = next(
                    (i + 1 for i, c in enumerate(unblocked_sorted) if c.soldier_id == assigned_id),
                    None,
                )
                assigned_c = next(
                    (c for c in unblocked if c.soldier_id == assigned_id), None
                )
                da.norm_score_before = assigned_c.pre_effort_score if assigned_c else None
                da.norm_score_after = assigned_c.post_effort_score if assigned_c else None
                da.candidate_rank = candidate_rank
                da.candidate_pool_size = pool_size

                payload = _explanation_payload(exp, dm_view=True, soldier_names=soldier_names)
                payload["global_before"] = explanation_data.global_metrics_before
                payload["global_after"] = explanation_data.global_metrics_after
                session.add(AssignmentExplanation(
                    duty_assignment_id=da.id,
                    payload=payload,
                    algorithm_version=explanation_data.algorithm_version,
                    solver_seed=str(explanation_data.solver_seed),
                ))

    _pr_phase("pass2 explanations added")
    if primary_assignments and reserve_assignments and soldier_node is not None:
        links = link_reserves(
            primary_assignments=primary_assignments,
            reserve_assignments=reserve_assignments,
            soldier_node=soldier_node,
            hierarchy_parent=hierarchy_parent or {},
            hierarchy_children=hierarchy_children or {},
        )
        for link in links:
            session.add(DutyReserveLink(
                reserve_assignment_id=link.reserve_assignment_id,
                primary_assignment_id=link.primary_assignment_id,
                hierarchy_distance=link.hierarchy_distance,
            ))
    _pr_phase("persist_results complete (pre-commit)")


def _count_proposals_for_job(session: Session, job: AlgorithmJob) -> int:
    """Count proposals created for a job via the audit log."""
    from sqlalchemy import func

    from app.db.models import AuditLog
    return session.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "algorithm.proposal.create",
            AuditLog.context["job_id"].astext == str(job.id),
        )
    ).scalar_one()


def resolve_solver_settings(session: Session, settings_json: dict) -> SolverSettings:
    """Build SolverSettings from per-run overrides layered over system-setting defaults.

    Per-run keys in settings_json win; system settings win over dataclass defaults.
    """
    from app.services.settings_loader import get_setting

    def _setting_int(key: str, default: int) -> int:
        try:
            return int(get_setting(session, key))
        except Exception:
            return default

    def _setting_decimal(key: str, default: str) -> Decimal:
        try:
            return Decimal(str(get_setting(session, key)))
        except Exception:
            return Decimal(default)

    def _setting_bool(key: str, default: bool) -> bool:
        try:
            return bool(get_setting(session, key))
        except Exception:
            return default

    def _setting_str(key: str, default: str) -> str:
        try:
            return str(get_setting(session, key))
        except Exception:
            return default

    return SolverSettings(
        T=int(settings_json.get("T", _setting_int("algorithm.max_duties_per_window", 8))),
        R=int(settings_json.get("R", _setting_int("algorithm.max_total_duties_per_window", 15))),
        Wt=int(settings_json.get("Wt", settings_json.get("W", _setting_int("algorithm.window_t", 14)))),
        Wr=int(settings_json.get("Wr", settings_json.get("W", _setting_int("algorithm.window_r", 28)))),
        alpha=Decimal(str(settings_json.get("alpha", 1.0))),
        time_limit_seconds=int(settings_json.get("time_limit_seconds", 60)),
        reserve_hierarchy_weight=_setting_decimal("fairness.reserve_hierarchy_weight", "0.5"),
        effort_resolution=_setting_int("fairness.effort_resolution", 20_000),
        batching_enabled=_setting_bool("algorithm.batching_enabled", True),
        batch_window_days=_setting_int("algorithm.batch_window_days", 28),
        batch_time_limit_seconds=_setting_int("algorithm.batch_time_limit_seconds", 120),
        relax_t_ceiling=int(settings_json.get("relax_t_ceiling", _setting_int("algorithm.relax_t_ceiling", 10))),
        relax_r_ceiling=int(settings_json.get("relax_r_ceiling", _setting_int("algorithm.relax_r_ceiling", 20))),
        decomposition=str(settings_json.get("decomposition", _setting_str("algorithm.decomposition", "interleaved"))),
        round_soldier_count=int(settings_json.get("round_soldier_count", _setting_int("algorithm.round_soldier_count", 20))),
        interleaved_batch_size=int(settings_json.get("interleaved_batch_size", _setting_int("algorithm.interleaved_batch_size", 50))),
        num_workers=int(settings_json.get("num_workers", 1)),
        tiebreak_mode=str(settings_json.get("tiebreak_mode", _setting_str("algorithm.tiebreak_mode", "range"))),
        tiebreak_time_limit_seconds=int(settings_json.get("tiebreak_time_limit_seconds", _setting_int("algorithm.tiebreak_time_limit_seconds", 20))),
        auto_relax_node_quotas=bool(settings_json.get(
            "auto_relax_node_quotas", _setting_bool("algorithm.auto_relax_node_quotas", False)
        )),
        enforce_weapon_qualification=bool(settings_json.get(
            "enforce_weapon_qualification", _setting_bool("weapon_qualification.enforce_eligibility", True)
        )),
    )


def _postprocess_batch_results(
    batch_results: list,
    block_to_shift: dict[uuid.UUID, uuid.UUID],
) -> list:
    """Replace per-block BatchShiftFill entries with per-shift aggregates.

    The solver stores block.id in BatchShiftFill.shift_id as a temporary stand-in.
    This function groups by real shift UUID and sums required/assigned counts.
    Returns a new list of BatchResult with aggregated shifts.
    """
    processed = []
    for br in batch_results:
        shift_required: dict[uuid.UUID, int] = {}
        shift_assigned: dict[uuid.UUID, int] = {}
        shift_fills: dict[uuid.UUID, list[BatchShiftFill]] = {}
        for sf in br.shifts:
            if sf.shift_id is None:
                continue
            # sf.shift_id is a block UUID; look up the real DutyShift UUID
            real_shift_id = block_to_shift.get(sf.shift_id, sf.shift_id)
            shift_required[real_shift_id] = shift_required.get(real_shift_id, 0) + sf.required_count
            shift_assigned[real_shift_id] = shift_assigned.get(real_shift_id, 0) + sf.assigned_count
            shift_fills.setdefault(real_shift_id, []).append(sf)

        aggregated_shifts = [
            BatchShiftFill(
                shift_id=sid,
                required_count=req,
                assigned_count=shift_assigned.get(sid, 0),
                eligible_count=max(sf.eligible_count for sf in shift_fills[sid]),
                available_count=max(sf.available_count for sf in shift_fills[sid]),
                blocker_counts={
                    key: max(sf.blocker_counts.get(key, 0) for sf in shift_fills[sid])
                    for key in {key for sf in shift_fills[sid] for key in sf.blocker_counts}
                },
            )
            for sid, req in shift_required.items()
        ]
        remapped_clusters = [
            dataclasses.replace(
                sc, shift_ids=[block_to_shift.get(sid, sid) for sid in sc.shift_ids]
            )
            for sc in br.saturation_clusters
        ]
        processed.append(dataclasses.replace(
            br, shifts=aggregated_shifts, saturation_clusters=remapped_clusters,
        ))
    return processed


def _br_to_dict(br) -> dict:
    """Serialise a BatchResult to a JSONB-compatible dict."""
    return {
        "batch_index": br.batch_index,
        "component_index": br.component_index,
        "date_from": br.date_from.isoformat(),
        "date_to": br.date_to.isoformat(),
        "duty_count": br.duty_count,
        "soldier_count": br.soldier_count,
        "assigned_count": br.assigned_count,
        "unassigned_count": br.unassigned_count,
        "outcome": br.outcome,
        "relaxations": br.relaxations,
        "wall_time_seconds": br.wall_time_seconds,
        "shifts": [
            {
                "shift_id": str(sf.shift_id) if sf.shift_id else None,
                "required_count": sf.required_count,
                "assigned_count": sf.assigned_count,
                "eligible_count": sf.eligible_count,
                "available_count": sf.available_count,
                "blocker_counts": sf.blocker_counts,
            }
            for sf in br.shifts
        ],
        "saturation_clusters": [
            {
                "date_from": sc.date_from.isoformat(),
                "date_to": sc.date_to.isoformat(),
                "shift_ids": [str(sid) for sid in sc.shift_ids],
                "eligible_pool_size": sc.eligible_pool_size,
                "free_count": sc.free_count,
                "competing_duty_types": [
                    {"duty_type_id": str(dt), "count": count} for dt, count in sc.competing_duty_types
                ],
            }
            for sc in br.saturation_clusters
        ],
        "impacted_soldiers": br.impacted_soldiers,
    }


def _identify_relaxation_impacts(
    result: SolverResult,
    duties: list[DutyBlock],
    existing: list[ExistingAssignment],
    settings: SolverSettings,
    soldier_names: dict[uuid.UUID, str],
    duty_type_names: dict[uuid.UUID, str],
    duty_to_batch: dict[uuid.UUID, int],
) -> dict[int, list[dict]]:
    """Return {batch_index: [impact_entry]} for assignments that exceeded base R/T caps.

    For each batch that required relaxation (br.relaxations non-empty), checks each
    assignment in that batch. An assignment is "impacted" when the soldier's cumulative
    duty days — existing pre-job assignments plus all new assignments up to and including
    this batch — exceed the base settings.R (Wr-day window) or settings.T (Wt-day window).
    """
    import bisect
    from datetime import timedelta as _td

    duty_map = {d.id: d for d in duties}

    relaxed_batch_indices = {br.batch_index for br in result.batch_results if br.relaxations}
    if not relaxed_batch_indices:
        return {}

    def _expand(start: date, end: date) -> list[date]:
        """Dates in [start, end) — mirrors _duty_dates convention."""
        days: list[date] = []
        cur = start
        while cur < end:
            days.append(cur)
            cur += _td(days=1)
        return days

    def _max_days_in_window(sorted_days: list[date], ref: date, W: int) -> int:
        """Max duty-day count in any W-day window containing `ref`, using bisect."""
        best = 0
        for offset in range(W):
            ws = ref - _td(days=offset)
            we = ws + _td(days=W - 1)
            cnt = bisect.bisect_right(sorted_days, we) - bisect.bisect_left(sorted_days, ws)
            if cnt > best:
                best = cnt
        return best

    # Pre-build per-soldier existing day lists (sorted, for bisect)
    existing_all: dict[uuid.UUID, list[date]] = {}
    existing_real: dict[uuid.UUID, list[date]] = {}
    for ea in existing:
        days = _expand(ea.start_date, ea.end_date)
        existing_all.setdefault(ea.soldier_id, []).extend(days)
        if not ea.is_reserve:
            existing_real.setdefault(ea.soldier_id, []).extend(days)

    # Pre-expand each duty block's dates exactly once
    duty_days_cache: dict[uuid.UUID, list[date]] = {
        a.duty_id: _expand(duty_map[a.duty_id].start_date, duty_map[a.duty_id].end_date)
        for a in result.assignments
        if a.duty_id in duty_map
    }

    impacts: dict[int, list[dict]] = {}

    for batch_idx in relaxed_batch_indices:
        # Pre-compute cumulative sorted day-lists per soldier up to this batch (once per batch)
        soldier_all: dict[uuid.UUID, list[date]] = {}
        soldier_real: dict[uuid.UUID, list[date]] = {}
        for a in result.assignments:
            if duty_to_batch.get(a.duty_id, -1) > batch_idx:
                continue
            duty = duty_map.get(a.duty_id)
            if duty is None:
                continue
            days = duty_days_cache[a.duty_id]
            soldier_all.setdefault(a.soldier_id, list(existing_all.get(a.soldier_id, []))).extend(days)
            if not duty.is_reserve:
                soldier_real.setdefault(a.soldier_id, list(existing_real.get(a.soldier_id, []))).extend(days)

        # Sort once per soldier (for bisect in _max_days_in_window)
        sorted_all = {sid: sorted(days) for sid, days in soldier_all.items()}
        sorted_real = {sid: sorted(days) for sid, days in soldier_real.items()}

        batch_impacts: list[dict] = []
        for a in result.assignments:
            if duty_to_batch.get(a.duty_id) != batch_idx:
                continue
            duty = duty_map.get(a.duty_id)
            if duty is None:
                continue

            r_count = _max_days_in_window(sorted_all.get(a.soldier_id, []), duty.start_date, settings.Wr)
            t_count = _max_days_in_window(sorted_real.get(a.soldier_id, []), duty.start_date, settings.Wt)

            violation: str | None = None
            if r_count > settings.R:
                violation = f"R={settings.R}→{r_count}"
            elif t_count > settings.T:
                violation = f"T={settings.T}→{t_count}"

            if violation:
                batch_impacts.append({
                    "soldier_id": str(a.soldier_id),
                    "soldier_name": soldier_names.get(a.soldier_id, str(a.soldier_id)[:8]),
                    "duty_type_name": duty_type_names.get(duty.duty_type_id, ""),
                    "start_date": duty.start_date.isoformat(),
                    "end_date": duty.end_date.isoformat(),
                    "violation": violation,
                })

        if batch_impacts:
            impacts[batch_idx] = batch_impacts

    return impacts


def run_algorithm_job(job_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    """Background task: load data, run solver, persist results."""
    import logging
    import time as _time
    import traceback

    from app.algorithm.explain import build_explanations
    from app.algorithm.reserve import compute_reserve_dist
    from app.algorithm.solver import solve
    from app.db.session import session_scope
    from app.services.settings_loader import get_setting

    _log = logging.getLogger(__name__)
    _t0 = _time.monotonic()

    def _phase(label: str) -> None:
        _log.info("[job %s] phase=%-30s elapsed=%.1fs", job_id, label, _time.monotonic() - _t0)

    cancel_event = threading.Event()
    _cancel_events[str(job_id)] = cancel_event

    try:
        with session_scope() as session:
            job = session.get(AlgorithmJob, job_id)
            if job is None:
                return

            # Job cancelled before background task started
            if job.status == "failed":
                return

            job.status = "running"
            job.started_at = datetime.now(tz=UTC)
            session.commit()

            try:
                settings = resolve_solver_settings(session, job.settings_json)

                def _setting_decimal(key: str, default: str) -> Decimal:
                    try:
                        return Decimal(str(get_setting(session, key)))
                    except Exception:
                        return Decimal(default)

                standby_multiplier = _setting_decimal("scoring.reserve_standby_multiplier", "0.2")

                shift_ids = [uuid.UUID(s) for s in job.shift_ids]
                _phase("load_duty_blocks: start")
                duties, block_to_shift_map = load_duty_blocks_from_shifts(
                    session, shift_ids=shift_ids, standby_multiplier=standby_multiplier,
                )
                _phase(f"load_duty_blocks: done ({len(duties)} blocks)")

                try:
                    configured_max_job_seconds = float(get_setting(session, "algorithm.max_job_seconds"))
                except Exception:
                    configured_max_job_seconds = 600.0
                # A flat budget doesn't scale with workload: the solver decomposes into
                # roughly len(duties)/interleaved_batch_size sequential batches, each
                # allowed up to batch_time_limit_seconds. Extend the watchdog (never
                # shrink below the configured floor) to cover that worst case, plus
                # headroom for setup/persisting, so an honestly large job isn't killed
                # before it can finish.
                estimated_batches = max(1, math.ceil(len(duties) / max(1, settings.interleaved_batch_size)))
                estimated_worst_case_seconds = estimated_batches * settings.batch_time_limit_seconds + 60
                max_job_seconds = max(configured_max_job_seconds, estimated_worst_case_seconds)
                threading.Thread(
                    target=_watch_job_timeout, args=(job_id, cancel_event, max_job_seconds), daemon=True,
                ).start()

                if not duties:
                    # Every selected shift is already fully staffed (published or
                    # pending draft) — there is nothing to assign. Finish cleanly
                    # rather than failing, and surface a clear reason for the UI.
                    job.status = "done"
                    job.progress_message = json.dumps({"pct": 100, "label": "הושלם"})
                    job.error_message = json.dumps({
                        "status": "NOTHING_TO_ASSIGN",
                        "reasons": ["כל המשמרות שנבחרו כבר מאוישות במלואן — אין מה לשבץ."],
                    })
                    job.finished_at = datetime.now(tz=UTC)
                    if job.created_by:
                        from app.db.models import NotificationType
                        from app.services.notifications import create_notification
                        create_notification(
                            session, soldier_id=job.created_by,
                            type=NotificationType.algorithm_job_done,
                            title="הרצת האלגוריתם הסתיימה — אין מה לשבץ",
                            reference_type="algorithm_job", reference_id=job.id,
                        )
                    session.commit()
                    return

                planning_start = min(d.start_date for d in duties)
                planning_end = max(d.end_date for d in duties)

                _phase("load_soldier_inputs: start")
                soldiers = load_soldier_inputs(
                    session, as_of=planning_start,
                    eligible_node_ids=job.settings_json.get("eligible_node_ids"),
                )
                _phase(f"load_soldier_inputs: done ({len(soldiers)} soldiers)")

                _phase("weapon_eligibility: start")
                populate_eligibility_data(session, soldiers=soldiers, duties=duties, settings=settings)
                _phase("weapon_eligibility: done")
                _phase("future_eligibility: done")

                # Compute and inject quarterly effort scores
                try:
                    _reset_raw = get_setting(session, "fairness.reset_date")
                    _reset_date = date.fromisoformat(str(_reset_raw))
                except Exception:
                    # Default: 2 years ago aligned to nearest quarter start
                    _reset_date = quarter_start(date(planning_start.year - 2, planning_start.month, 1))
                # Count ALL published commitments — past and future — so duties
                # already published months ahead raise the soldier's effort and
                # deprioritise them for new work (see effort_history_horizon).
                effort_horizon = effort_history_horizon(session, planning_start=planning_start)
                _phase("compute_effort_data: start")
                effort_map = compute_effort_data(
                    session,
                    soldiers=soldiers,
                    planning_start=effort_horizon,
                    planning_end=effort_horizon,
                    reset_date=_reset_date,
                    pending_duties=duties,
                )
                _phase("compute_effort_data: done")
                # Whole-job range, for the _count_space_stats diagnostics only (those
                # report a single before/after CV across the entire run). The solve
                # itself does NOT use this — each batch's build_model call auto-derives
                # its own tighter range from just the soldiers/duties it actually sees
                # (see model.py's range_size<=0 fallback), since stamping this global,
                # whole-job range onto every batch needlessly inflates the denominator
                # for any batch smaller than the full run, pushing duty weights toward
                # the max(1, ...) floor more than necessary.
                stats_range_min, stats_range_max = inject_effort_scores(soldiers, duties, effort_map)
                _log.info(
                    "[job %s] effort_range min=%d max=%d; sample soldier efforts: %s",
                    job_id, stats_range_min, stats_range_max,
                    [(s.id, s.effort_offset, s.effort_per_milli) for s in soldiers[:5]],
                )
                stats_before = _count_space_stats(soldiers, [], duties, settings.effort_resolution,
                                                  stats_range_min, stats_range_max)
                existing = load_existing_assignments(
                    session,
                    planning_start=planning_start,
                    planning_end=planning_end,
                    W=settings.Wr,
                )

                if not soldiers:
                    job.status = "failed"
                    job.error_message = "no_soldiers_or_duties"
                    job.finished_at = datetime.now(tz=UTC)
                    if job.created_by:
                        from app.db.models import NotificationType
                        from app.services.notifications import create_notification
                        create_notification(
                            session, soldier_id=job.created_by,
                            type=NotificationType.algorithm_job_failed,
                            title="הרצת האלגוריתם נכשלה — אין חיילים זמינים",
                            reference_type="algorithm_job", reference_id=job.id,
                        )
                    session.commit()
                    return

                _phase("solver_input_snapshot: start")
                job.solver_input_snapshot = serialize_solver_inputs(
                    job_id=job.id,
                    planning_start=planning_start,
                    planning_end=planning_end,
                    settings=settings,
                    soldiers=soldiers,
                    duties=duties,
                    existing=existing,
                    block_to_shift_map=block_to_shift_map,
                )
                session.commit()
                _phase("solver_input_snapshot: done")

                hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)

                _phase("compute_reserve_dist: start")
                reserve_dist = compute_reserve_dist(
                    soldiers=soldiers, duties=duties, block_to_shift=block_to_shift_map,
                    hierarchy_parent=hier_parent, soldier_node=soldier_node,
                )
                _phase("compute_reserve_dist: done")

                # Real-time progress: the solver decomposes the run into batches and
                # calls this back once with (0, total) then after each duty batch.
                # Both arguments are DUTY counts, so the bar advances proportionally
                # to work done.  5–93 % leaves room for the swap pass and persisting.
                def _report_progress(done: int, total: int) -> None:
                    total = max(total, 1)
                    pct = 5 + int(88 * done / total)
                    label = (
                        f"פותר — {done} מתוך {total} תורנויות" if done > 0
                        else f"מתחיל לפתור — {total} תורנויות"
                    )
                    job.progress_message = json.dumps({"pct": pct, "label": label})
                    session.commit()

                def _report_swap_start() -> None:
                    job.progress_message = json.dumps({"pct": 94, "label": "מאזן עומסים…"})
                    session.commit()

                job.progress_message = json.dumps({"pct": 3, "label": "מכין נתונים…"})
                session.commit()

                _phase("solver: start")
                _log.info(
                    "[job %s] calling solve() — %d soldiers, %d duties, %d existing",
                    job_id, len(soldiers), len(duties), len(existing),
                )
                node_parents = _build_node_parents(hier_parent) if settings.auto_relax_node_quotas else None
                try:
                    result = solve(
                        soldiers, duties, existing, settings,
                        reserve_dist=reserve_dist, cancel_event=cancel_event,
                        progress_cb=_report_progress,
                        swap_progress_cb=_report_swap_start,
                        node_parents=node_parents,
                    )
                except BaseException as _solve_exc:
                    _log.critical(
                        "[job %s] solve() raised %s:\n%s",
                        job_id, type(_solve_exc).__name__,
                        traceback.format_exc(),
                    )
                    raise
                _phase(f"solver: done (status={result.status}, assignments={len(result.assignments)})")
                job.progress_message = json.dumps({"pct": 96, "label": "שומר הצעות…"})
                session.commit()

                # Solver was interrupted by cancellation (timeout watchdog or explicit
                # user cancel both set cancel_event the same way — the DB row already
                # has whichever terminal status/error_message that path committed).
                # With nothing assigned before the cutoff there's nothing to salvage.
                salvaging_timeout = False
                if result.status == "CANCELLED" and not result.assignments:
                    session.rollback()
                    return
                if result.status == "CANCELLED":
                    session.refresh(job)
                    if job.error_message == "cancelled_by_user":
                        # The user asked to stop, not to get a draft of whatever
                        # finished first — honor the cancellation as-is.
                        session.rollback()
                        return
                    # Timed out, but earlier batches/components completed before the
                    # cutoff — treat their work as a partial result instead of
                    # discarding it. Falls through to the normal persistence path
                    # below, which will mark the job "done" with a PARTIAL note.
                    salvaging_timeout = True

                if result.status == "INFEASIBLE":
                    from app.algorithm.diagnose import diagnose_infeasibility
                    dt_names = {
                        dt.id: dt.name
                        for dt in session.execute(select(DutyType)).scalars().all()
                    }
                    reasons = diagnose_infeasibility(soldiers, duties, existing, dt_names)
                    job.status = "failed"
                    job.error_message = json.dumps({
                        "relaxed": result.relaxed,
                        "status": "INFEASIBLE",
                        "reasons": reasons,
                    })
                    processed = _postprocess_batch_results(result.batch_results, block_to_shift_map)
                    job.batch_results = [_br_to_dict(br) for br in processed]
                    job.finished_at = datetime.now(tz=UTC)
                    if job.created_by:
                        from app.db.models import NotificationType
                        from app.services.notifications import create_notification
                        create_notification(
                            session, soldier_id=job.created_by,
                            type=NotificationType.algorithm_job_failed,
                            title="הרצת האלגוריתם נכשלה — לא נמצא פתרון אפשרי",
                            body="; ".join(reasons[:3]) if reasons else None,
                            reference_type="algorithm_job", reference_id=job.id,
                        )
                    session.commit()
                    return

                # Build duty_id (block UUID) → batch_index map for stamping on DutyAssignment rows
                duty_to_batch: dict[uuid.UUID, int] = {}
                for br in result.batch_results:
                    for sf in br.shifts:
                        if sf.shift_id is not None:
                            duty_to_batch[sf.shift_id] = br.batch_index

                stats_after = _count_space_stats(soldiers, result.assignments, duties, settings.effort_resolution,
                                                 stats_range_min, stats_range_max)

                _phase("build_explanations: start")
                explanation_data = build_explanations(
                    soldiers=soldiers,
                    duties=duties,
                    assignments=result.assignments,
                    global_before=stats_before,
                    global_after=stats_after,
                    solver_seed=result.seed,
                )
                _phase("build_explanations: done")

                soldier_names = {
                    s.id: s.full_name
                    for s in session.execute(select(Soldier)).scalars().all()
                }

                # Lazy DutyType name fetch — shared by relaxation impacts and partial diagnosis
                _dt_names_cache: dict[uuid.UUID, str] | None = None

                def _get_dt_names() -> dict[uuid.UUID, str]:
                    nonlocal _dt_names_cache
                    if _dt_names_cache is None:
                        _dt_names_cache = {
                            dt.id: dt.name
                            for dt in session.execute(select(DutyType)).scalars().all()
                        }
                    return _dt_names_cache

                # Annotate result.batch_results before serialization
                if result.relaxed:
                    _impacts = _identify_relaxation_impacts(
                        result, duties, existing, settings, soldier_names,
                        _get_dt_names(), duty_to_batch,
                    )
                    for _i, _br in enumerate(result.batch_results):
                        if _br.batch_index in _impacts:
                            result.batch_results[_i] = dataclasses.replace(
                                _br, impacted_soldiers=_impacts[_br.batch_index]
                            )

                # Post-process and serialize (impacted_soldiers now included via _br_to_dict)
                processed_batch_results = _postprocess_batch_results(
                    result.batch_results, block_to_shift_map
                )
                job.batch_results = [_br_to_dict(br) for br in processed_batch_results]

                _phase("persist_results: start")
                persist_results(
                    session,
                    job=job,
                    result=result,
                    explanation_data=explanation_data,
                    duty_blocks=duties,
                    soldier_names=soldier_names,
                    actor_id=actor_id,
                    block_to_shift_map=block_to_shift_map,
                    hierarchy_parent=hier_parent,
                    hierarchy_children=hier_children,
                    soldier_node=soldier_node,
                    duty_to_batch=duty_to_batch,
                )
                _phase("persist_results: done")

                # Check if the job was cancelled by something other than the timeout
                # we're already deliberately salvaging (e.g. a user cancel that landed
                # while persist_results was running).
                session.refresh(job)
                if job.status == "failed" and not salvaging_timeout:
                    # Cancelled externally — don't overwrite the cancellation
                    session.rollback()
                    return

                # Attach diagnostic reasons when the result is partial (some duties unassigned)
                assigned_ct = len(result.assignments)
                if assigned_ct < len(duties) or salvaging_timeout:
                    from app.algorithm.diagnose import diagnose_infeasibility
                    reasons = diagnose_infeasibility(soldiers, duties, existing, _get_dt_names())
                    job.error_message = json.dumps({
                        "status": "PARTIAL",
                        "assigned": assigned_ct,
                        "total": len(duties),
                        "relaxed": result.relaxed,
                        "reasons": reasons,
                        "timed_out": salvaging_timeout,
                    })

                job.result_metadata = {
                    "fairness_before": stats_before,
                    "fairness_after": stats_after,
                    "outcome": result.status,
                    "objective_value": result.objective_value,
                    "solver_metrics": result.solver_metrics,
                }
                job.status = "done"
                job.finished_at = datetime.now(tz=UTC)
                _phase("job marked done, pre-final-commit")

                if job.created_by:
                    from app.db.models import NotificationType
                    from app.services.notifications import create_notification
                    proposal_count = _count_proposals_for_job(session, job)
                    create_notification(
                        session,
                        soldier_id=job.created_by,
                        type=NotificationType.algorithm_job_done,
                        title=f"הרצת האלגוריתם הסתיימה — {proposal_count} הצעות ממתינות לאישור",
                        reference_type="algorithm_job",
                        reference_id=job.id,
                    )

                session.commit()
                _phase("final commit done — job complete")

            except Exception as exc:  # noqa: BLE001
                _log.error(
                    "[job %s] unhandled exception in run_algorithm_job:\n%s",
                    job_id, traceback.format_exc(),
                )
                session.rollback()
                with session_scope() as err_session:
                    err_job = err_session.get(AlgorithmJob, job_id)
                    if err_job is not None:
                        err_job.status = "failed"
                        err_job.error_message = str(exc)
                        err_job.finished_at = datetime.now(tz=UTC)

                        if err_job.created_by:
                            from app.db.models import NotificationType
                            from app.services.notifications import create_notification
                            body = str(exc)[:200] if str(exc) else None
                            create_notification(
                                err_session,
                                soldier_id=err_job.created_by,
                                type=NotificationType.algorithm_job_failed,
                                title="הרצת האלגוריתם נכשלה",
                                body=body,
                                reference_type="algorithm_job",
                                reference_id=err_job.id,
                            )

                        err_session.commit()
    finally:
        _cancel_events.pop(str(job_id), None)


def serialize_solver_inputs(
    *,
    job_id: uuid.UUID,
    planning_start: date,
    planning_end: date,
    settings: SolverSettings,
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    existing: list[ExistingAssignment],
    block_to_shift_map: dict[uuid.UUID, uuid.UUID],
) -> dict:
    """Build the JSON-serializable solver-input dump shape.

    Shared by run_algorithm_job (to persist a snapshot at solve time) and
    export_solver_inputs (to return it later, or to live-reconstruct for jobs
    that predate the snapshot).
    """

    def _soldier_dict(s: SoldierInput) -> dict:
        return {
            "id": str(s.id),
            "enrolled_at": s.enrolled_at.isoformat(),
            "cumulative_score": float(s.cumulative_score),
            "active_days": s.active_days,
            "hierarchy_node_id": str(s.hierarchy_node_id) if s.hierarchy_node_id else None,
            "approved_constraint_dates": [
                [a.isoformat(), b.isoformat()] for a, b in s.approved_constraint_dates
            ],
            "exempted_duty_type_ids": [str(e) for e in s.exempted_duty_type_ids],
            "effort_offset": s.effort_offset,
            "effort_per_milli": s.effort_per_milli,
        }

    def _duty_dict(d: DutyBlock) -> dict:
        return {
            "id": str(d.id),
            "duty_type_id": str(d.duty_type_id),
            "duty_location_id": str(d.duty_location_id),
            "start_date": d.start_date.isoformat(),
            "end_date": d.end_date.isoformat(),
            "score_per_day": float(d.score_per_day),
            "is_reserve": d.is_reserve,
            "eligible_node_ids": [str(n) for n in d.eligible_node_ids] if d.eligible_node_ids else None,
            "shift_id": str(block_to_shift_map[d.id]) if d.id in block_to_shift_map else None,
        }

    def _existing_dict(e: ExistingAssignment) -> dict:
        return {
            "soldier_id": str(e.soldier_id),
            "duty_type_id": str(e.duty_type_id),
            "start_date": e.start_date.isoformat(),
            "end_date": e.end_date.isoformat(),
            "is_reserve": e.is_reserve,
        }

    settings_dict = dataclasses.asdict(settings)
    settings_dict["alpha"] = float(settings_dict["alpha"])
    settings_dict["reserve_hierarchy_weight"] = float(settings_dict["reserve_hierarchy_weight"])

    return {
        "job_id": str(job_id),
        "planning_start": planning_start.isoformat(),
        "planning_end": planning_end.isoformat(),
        "exported_at": datetime.now(tz=UTC).isoformat(),
        "settings": settings_dict,
        "soldiers": [_soldier_dict(s) for s in soldiers],
        "duties": [_duty_dict(d) for d in duties],
        "existing_assignments": [_existing_dict(e) for e in existing],
    }


def _export_solver_outputs(job: "AlgorithmJob", session: "Session") -> dict:
    """Return the solver outputs for this job: batch results, metadata, and proposals."""
    from app.db.models import DutyAssignment
    from sqlalchemy import select

    proposals_q = select(DutyAssignment).where(DutyAssignment.algorithm_job_id == job.id)
    proposals = session.execute(proposals_q).scalars().all()

    def _assignment_dict(a: "DutyAssignment") -> dict:
        return {
            "id": str(a.id),
            "soldier_id": str(a.soldier_id),
            "duty_type_id": str(a.duty_type_id),
            "duty_location_id": str(a.duty_location_id),
            "start_date": a.start_date.isoformat(),
            "end_date": a.end_date.isoformat(),
            "start_time": a.start_time,
            "end_time": a.end_time,
            "status": a.status,
            "is_reserve": a.is_reserve,
            "batch_index": a.batch_index,
            "duty_shift_id": str(a.duty_shift_id) if a.duty_shift_id else None,
            "norm_score_before": a.norm_score_before,
            "norm_score_after": a.norm_score_after,
        }

    return {
        "batch_results": job.batch_results or [],
        "result_metadata": job.result_metadata or {},
        "proposals": [_assignment_dict(a) for a in proposals],
    }


def export_solver_inputs(job: "AlgorithmJob", session: "Session") -> dict:
    """Return this job's solver inputs and outputs for offline debugging.

    If a snapshot was captured at run time (jobs created after the
    solver_input_snapshot column was added), return it verbatim with a fresh
    exported_at timestamp — this is the only path that reflects the duties
    actually solved, since by the time a job is done, load_duty_blocks_from_shifts
    no longer finds anything to (re)generate (its slots are filled). For
    legacy jobs with no snapshot, fall back to live reconstruction (best-effort;
    will return empty duties for a completed legacy job whose shifts are filled).
    """
    outputs = _export_solver_outputs(job, session)

    if job.solver_input_snapshot is not None:
        return {
            **job.solver_input_snapshot,
            "exported_at": datetime.now(tz=UTC).isoformat(),
            **outputs,
        }

    from app.services.settings_loader import get_setting

    settings = resolve_solver_settings(session, job.settings_json)

    def _setting_decimal(key: str, default: str) -> Decimal:
        try:
            return Decimal(str(get_setting(session, key)))
        except Exception:
            return Decimal(default)

    standby_multiplier = _setting_decimal("scoring.reserve_standby_multiplier", "0.2")

    shift_ids = [uuid.UUID(s) for s in job.shift_ids]
    duties, block_to_shift_map = load_duty_blocks_from_shifts(
        session, shift_ids=shift_ids, standby_multiplier=standby_multiplier,
    )

    if duties:
        planning_start = min(d.start_date for d in duties)
        planning_end = max(d.end_date for d in duties)
    else:
        planning_start = job.planning_start
        planning_end = job.planning_end

    soldiers = load_soldier_inputs(
        session, as_of=planning_start,
        eligible_node_ids=job.settings_json.get("eligible_node_ids"),
    )

    try:
        _reset_raw = get_setting(session, "fairness.reset_date")
        _reset_date = date.fromisoformat(str(_reset_raw))
    except Exception:
        _reset_date = quarter_start(date(planning_start.year - 2, planning_start.month, 1))

    effort_horizon = effort_history_horizon(session, planning_start=planning_start)
    effort_map = compute_effort_data(
        session,
        soldiers=soldiers,
        planning_start=effort_horizon,
        planning_end=effort_horizon,
        reset_date=_reset_date,
    )
    # Side effects only (effort_offset/effort_per_milli per soldier). The returned
    # whole-job range is intentionally NOT stamped onto settings — see the matching
    # comment in run_algorithm_job: each batch derives its own tighter range.
    inject_effort_scores(soldiers, duties, effort_map)

    existing = load_existing_assignments(
        session,
        planning_start=planning_start,
        planning_end=planning_end,
        W=settings.Wr,
    )

    return {
        **serialize_solver_inputs(
            job_id=job.id,
            planning_start=planning_start,
            planning_end=planning_end,
            settings=settings,
            soldiers=soldiers,
            duties=duties,
            existing=existing,
            block_to_shift_map=block_to_shift_map,
        ),
        **outputs,
    }
