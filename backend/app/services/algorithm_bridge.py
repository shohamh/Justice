from __future__ import annotations

import json
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import (
    Assignment,
    AssignmentExplanation as AlgoExplanation,
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


def load_soldier_inputs(session: Session, *, as_of: date) -> list[SoldierInput]:
    """Load every active soldier as a SoldierInput for the algorithm."""
    soldiers = (
        session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    )
    duty_scores = scoring_svc.duty_score_by_soldier(session)
    adj_scores = scoring_svc.adjustments_by_soldier(session)

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

    from app.db.models import SystemSetting
    from app.services.eligibility import compute_eligibility_exclusions

    def _setting_int(key: str, default: int) -> int:
        row = session.get(SystemSetting, key)
        if row is None:
            return default
        try:
            return int(row.value)
        except (TypeError, ValueError):
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
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))

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
    shifts = session.execute(select(DutyShift).where(DutyShift.id.in_(shift_ids))).scalars().all()

    type_ids = {s.duty_type_id for s in shifts}
    types_q = session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars().all()
    score_map = {dt.id: dt.score_per_day for dt in types_q}

    blocks: list[DutyBlock] = []
    block_to_shift: dict[uuid.UUID, uuid.UUID] = {}

    for shift in shifts:
        score = score_map.get(shift.duty_type_id, Decimal("1.00"))
        for _ in range(shift.required_count):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=shift.start_date,
                end_date=shift.end_date,
                score_per_day=score,
                is_reserve=False,
                eligible_node_ids=shift.eligible_node_ids,
            ))
            block_to_shift[block_id] = shift.id
        r_count = reserve_count_for_shift(session, shift=shift)
        r_score = score * standby_multiplier
        for _ in range(r_count):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=shift.start_date,
                end_date=shift.end_date,
                score_per_day=r_score,
                is_reserve=True,
                eligible_node_ids=shift.eligible_node_ids,
            ))
            block_to_shift[block_id] = shift.id

    return blocks, block_to_shift


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
    """Serialise one AssignmentExplanation to a JSON-safe dict."""
    candidates = []
    for c in exp.candidates:
        entry: dict[str, Any] = {
            "soldier_id": str(c.soldier_id),
            "blocked": c.blocked,
            "blocking_constraints": c.blocking_constraints,
        }
        if dm_view:
            entry["soldier_name"] = soldier_names.get(c.soldier_id, "")
            entry["pre_norm_score"] = float(c.pre_norm_score) if c.pre_norm_score is not None else None
            entry["post_norm_score"] = float(c.post_norm_score) if c.post_norm_score is not None else None
        candidates.append(entry)
    return {
        "duty_id": str(exp.duty_id),
        "assigned_soldier_id": str(exp.assigned_soldier_id),
        "tiebreaker_note": exp.tiebreaker_note,
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
) -> None:
    """Insert algorithm_draft assignments, explanations (primary only), and reserve links."""
    from app.algorithm.reserve import link_reserves

    duty_map = {d.id: d for d in duty_blocks}
    explanation_map = {e.duty_id: e for e in explanation_data.per_assignment}

    primary_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []
    reserve_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

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
        session.add(da)
        session.flush()  # populate da.id

        if not block.is_reserve:
            exp = explanation_map.get(a.duty_id)
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


def run_algorithm_job(job_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    """Background task: load data, run solver, persist results."""
    from app.algorithm.explain import build_explanations
    from app.algorithm.reserve import compute_reserve_dist
    from app.algorithm.solver import solve
    from app.db.session import session_scope
    from app.services.settings_loader import get_setting

    with session_scope() as session:
        job = session.get(AlgorithmJob, job_id)
        if job is None:
            return

        job.status = "running"
        job.started_at = datetime.now(tz=timezone.utc)
        session.commit()

        try:
            def _setting_decimal(key: str, default: str) -> Decimal:
                try:
                    return Decimal(str(get_setting(session, key)))
                except Exception:
                    return Decimal(default)

            settings = SolverSettings(
                K=Decimal(str(job.settings_json.get("K", 8))),
                T=int(job.settings_json.get("T", 7)),
                W=int(job.settings_json.get("W", 14)),
                alpha=Decimal(str(job.settings_json.get("alpha", 1.0))),
                beta=Decimal(str(job.settings_json.get("beta", 2.0))),
                time_limit_seconds=int(job.settings_json.get("time_limit_seconds", 30)),
                reserve_hierarchy_weight=_setting_decimal("fairness.reserve_hierarchy_weight", "0.5"),
            )
            standby_multiplier = _setting_decimal("scoring.reserve_standby_multiplier", "0.2")

            shift_ids = [uuid.UUID(s) for s in job.shift_ids]
            duties, block_to_shift_map = load_duty_blocks_from_shifts(
                session, shift_ids=shift_ids, standby_multiplier=standby_multiplier,
            )

            if not duties:
                job.status = "failed"
                job.error_message = "no_shifts_selected"
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            planning_start = min(d.start_date for d in duties)
            planning_end = max(d.end_date for d in duties)

            soldiers = load_soldier_inputs(session, as_of=planning_start)
            existing = load_existing_assignments(
                session,
                planning_start=planning_start,
                planning_end=planning_end,
                W=settings.W,
            )

            if not soldiers:
                job.status = "failed"
                job.error_message = "no_soldiers_or_duties"
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)

            reserve_dist = compute_reserve_dist(
                soldiers=soldiers, duties=duties, block_to_shift=block_to_shift_map,
                hierarchy_parent=hier_parent, soldier_node=soldier_node,
            )

            result = solve(soldiers, duties, existing, settings, reserve_dist=reserve_dist)

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
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            explanation_data = build_explanations(
                soldiers=soldiers,
                duties=duties,
                assignments=result.assignments,
                global_before={},
                global_after={},
                solver_seed=result.seed,
            )

            soldier_names = {
                s.id: s.full_name
                for s in session.execute(select(Soldier)).scalars().all()
            }

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
            )

            # Check if job was cancelled while the solver was running
            session.refresh(job)
            if job.status == "failed":
                # Cancelled externally — don't overwrite the cancellation
                session.rollback()
                return

            job.status = "done"
            job.finished_at = datetime.now(tz=timezone.utc)
            session.commit()

        except Exception as exc:  # noqa: BLE001
            session.rollback()
            with session_scope() as err_session:
                err_job = err_session.get(AlgorithmJob, job_id)
                if err_job is not None:
                    err_job.status = "failed"
                    err_job.error_message = str(exc)
                    err_job.finished_at = datetime.now(tz=timezone.utc)
                    err_session.commit()
