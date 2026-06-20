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
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
    SoldierExemption,
)
from app.services import scoring as scoring_svc
from app.services.effort_score import EFFORT_SCALE, EffortData, compute_effort_data, quarter_start

_cancel_events: dict[str, threading.Event] = {}


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


def load_soldier_inputs(session: Session, *, as_of: date) -> list[SoldierInput]:
    """Load every active soldier as a SoldierInput for the algorithm."""
    soldiers = (
        session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    )
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
    soldier_full_exempt_dates: dict[uuid.UUID, set[date]] = {}

    for ex in all_exemptions:
        # Active exemption check for duty-type resolution (as_of)
        if ex.start_date <= as_of and (ex.end_date is None or ex.end_date >= as_of):
            dtids = etid_to_dtids.get(ex.exemption_type_id, set())
            soldier_exempt_dtype_ids.setdefault(ex.soldier_id, set()).update(dtids)

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
        session, soldiers, mitvahim_months=mitvahim_months, alal_months=alal_months
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
                approved_constraint_dates=soldier_constraints.get(s.id, []),
                exempted_duty_type_ids=combined_exempt,
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

    blocks: list[DutyBlock] = []
    block_to_shift: dict[uuid.UUID, uuid.UUID] = {}
    today = date.today()

    for shift in shifts:
        effective_start = max(shift.start_date, today)
        if effective_start > shift.end_date:
            # Shift is entirely in the past — nothing left to assign
            continue
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
        for _ in range(primary_needed):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=effective_start,
                end_date=shift.end_date,
                score_per_day=score,
                is_reserve=False,
                eligible_node_ids=shift.eligible_node_ids,
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
                score_per_day=r_score,
                is_reserve=True,
                eligible_node_ids=shift.eligible_node_ids,
            ))
            block_to_shift[block_id] = shift.id

    return blocks, block_to_shift


def inject_effort_scores(
    soldiers: list[SoldierInput],
    duty_blocks: list[DutyBlock],
    effort_map: dict[uuid.UUID, EffortData],
) -> tuple[int, int]:
    """Set effort_offset and effort_per_milli on each SoldierInput in-place.

    effort_per_milli = int(C_over_D / unit_score_milli × EFFORT_SCALE)
    where unit_score_milli = sum of block_score(b) for all blocks in the planning window.

    Returns (effort_range_min, effort_range_max) — tight bounds covering every possible
    effort_offset value throughout the entire run (including worst-case accumulation).
    """
    unit_score_milli = sum(
        int(float(b.score_per_day) * ((b.end_date - b.start_date).days) * 1000)
        for b in duty_blocks
    )
    for s in soldiers:
        data = effort_map.get(s.id)
        if data is None:
            continue
        s.effort_offset = data.effort_offset
        if unit_score_milli > 0:
            s.effort_per_milli = int(float(data.C_over_D) / unit_score_milli * EFFORT_SCALE)
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
    return [
        ExistingAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
            is_reserve=a.is_reserve,
        )
        for a in rows
    ]


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
            status="algorithm_draft",
            created_by=actor_id,
            notes=None,
            duty_shift_id=shift_id,
            is_reserve=block.is_reserve,
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
        effort_resolution=_setting_int("fairness.effort_resolution", 1_000),
        batching_enabled=_setting_bool("algorithm.batching_enabled", True),
        batch_window_days=_setting_int("algorithm.batch_window_days", 28),
        batch_time_limit_seconds=_setting_int("algorithm.batch_time_limit_seconds", 60),
        relax_t_ceiling=int(settings_json.get("relax_t_ceiling", _setting_int("algorithm.relax_t_ceiling", 10))),
        relax_r_ceiling=int(settings_json.get("relax_r_ceiling", _setting_int("algorithm.relax_r_ceiling", 20))),
        decomposition=str(settings_json.get("decomposition", _setting_str("algorithm.decomposition", "effort_rounds"))),
        round_soldier_count=int(settings_json.get("round_soldier_count", _setting_int("algorithm.round_soldier_count", 20))),
        num_workers=int(settings_json.get("num_workers", 1)),
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
        for sf in br.shifts:
            if sf.shift_id is None:
                continue
            # sf.shift_id is a block UUID; look up the real DutyShift UUID
            real_shift_id = block_to_shift.get(sf.shift_id, sf.shift_id)
            shift_required[real_shift_id] = shift_required.get(real_shift_id, 0) + sf.required_count
            shift_assigned[real_shift_id] = shift_assigned.get(real_shift_id, 0) + sf.assigned_count

        aggregated_shifts = [
            BatchShiftFill(
                shift_id=sid,
                required_count=req,
                assigned_count=shift_assigned.get(sid, 0),
            )
            for sid, req in shift_required.items()
        ]
        processed.append(dataclasses.replace(br, shifts=aggregated_shifts))
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
            }
            for sf in br.shifts
        ],
    }


def run_algorithm_job(job_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    """Background task: load data, run solver, persist results."""
    import logging
    import time as _time

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
                    session.commit()
                    return

                planning_start = min(d.start_date for d in duties)
                planning_end = max(d.end_date for d in duties)

                _phase("load_soldier_inputs: start")
                soldiers = load_soldier_inputs(session, as_of=planning_start)
                _phase(f"load_soldier_inputs: done ({len(soldiers)} soldiers)")
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
                effort_map = compute_effort_data(
                    session,
                    soldiers=soldiers,
                    planning_start=effort_horizon,
                    planning_end=effort_horizon,
                    reset_date=_reset_date,
                )
                effort_range = inject_effort_scores(soldiers, duties, effort_map)
                settings.effort_range_min, settings.effort_range_max = effort_range
                stats_before = _count_space_stats(soldiers, [], duties, settings.effort_resolution,
                                                  settings.effort_range_min, settings.effort_range_max)
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
                    session.commit()
                    return

                hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)

                _phase("compute_reserve_dist: start")
                reserve_dist = compute_reserve_dist(
                    soldiers=soldiers, duties=duties, block_to_shift=block_to_shift_map,
                    hierarchy_parent=hier_parent, soldier_node=soldier_node,
                )
                _phase("compute_reserve_dist: done")

                # Real-time progress: the solver decomposes the run into batches and
                # calls this back once with (0, total) then after each batch.  We map
                # batches to 5–95 % (leaving headroom for setup and persisting) and
                # store a {pct, label} JSON on the job for the UI to poll.
                def _report_progress(done: int, total: int) -> None:
                    total = max(total, 1)
                    pct = 5 + int(90 * done / total)
                    label = (
                        f"פותר — אצווה {done} מתוך {total}" if done > 0
                        else f"מתחיל לפתור — {total} אצוות"
                    )
                    job.progress_message = json.dumps({"pct": pct, "label": label})
                    session.commit()

                job.progress_message = json.dumps({"pct": 3, "label": "מכין נתונים…"})
                session.commit()

                _phase("solver: start")
                result = solve(
                    soldiers, duties, existing, settings,
                    reserve_dist=reserve_dist, cancel_event=cancel_event,
                    progress_cb=_report_progress,
                )
                _phase(f"solver: done (status={result.status}, assignments={len(result.assignments)})")
                job.progress_message = json.dumps({"pct": 96, "label": "שומר הצעות…"})
                session.commit()

                # Solver was interrupted by cancellation — DB already marked failed
                if result.status == "CANCELLED":
                    session.rollback()
                    return

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
                    session.commit()
                    return

                # Post-process batch_results: replace block UUIDs with real DutyShift UUIDs
                processed_batch_results = _postprocess_batch_results(
                    result.batch_results, block_to_shift_map
                )

                # Serialise batch_results to JSONB-compatible list of dicts
                job.batch_results = [_br_to_dict(br) for br in processed_batch_results]

                # Build duty_id (block UUID) → batch_index map for stamping on DutyAssignment rows
                duty_to_batch: dict[uuid.UUID, int] = {}
                for br in result.batch_results:
                    for sf in br.shifts:
                        if sf.shift_id is not None:
                            duty_to_batch[sf.shift_id] = br.batch_index

                stats_after = _count_space_stats(soldiers, result.assignments, duties, settings.effort_resolution,
                                                 settings.effort_range_min, settings.effort_range_max)

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

                # Check if job was cancelled while the solver was running
                session.refresh(job)
                if job.status == "failed":
                    # Cancelled externally — don't overwrite the cancellation
                    session.rollback()
                    return

                # Attach diagnostic reasons when the result is partial (some duties unassigned)
                assigned_ct = len(result.assignments)
                if assigned_ct < len(duties):
                    from app.algorithm.diagnose import diagnose_infeasibility
                    dt_names = {
                        dt.id: dt.name
                        for dt in session.execute(select(DutyType)).scalars().all()
                    }
                    reasons = diagnose_infeasibility(soldiers, duties, existing, dt_names)
                    job.error_message = json.dumps({
                        "status": "PARTIAL",
                        "assigned": assigned_ct,
                        "total": len(duties),
                        "relaxed": result.relaxed,
                        "reasons": reasons,
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


def export_solver_inputs(job: "AlgorithmJob", session: "Session") -> dict:
    """Reconstruct solver inputs from a stored job and return as a JSON-serializable dict."""
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

    soldiers = load_soldier_inputs(session, as_of=planning_start)

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
    effort_range = inject_effort_scores(soldiers, duties, effort_map)
    settings.effort_range_min, settings.effort_range_max = effort_range

    existing = load_existing_assignments(
        session,
        planning_start=planning_start,
        planning_end=planning_end,
        W=settings.Wr,
    )

    return serialize_solver_inputs(
        job_id=job.id,
        planning_start=planning_start,
        planning_end=planning_end,
        settings=settings,
        soldiers=soldiers,
        duties=duties,
        existing=existing,
        block_to_shift_map=block_to_shift_map,
    )
