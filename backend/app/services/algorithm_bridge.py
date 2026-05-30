from __future__ import annotations

import json
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
    ReserveEntry,
    SoldierInput,
    SolverResult,
    SolverSettings,
)
from app.audit.writer import write_audit
from app.db.models import (
    AlgorithmJob,
    AssignmentExplanation,
    DutyAssignment,
    DutyType,
    ExemptionDutyTypeMap,
    HierarchyNode,
    PersonalConstraint,
    ReserveAssignment,
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

    # Determine which exemption types provide full coverage (cover ALL active duty types)
    active_dt_ids: set[uuid.UUID] = set(
        session.execute(select(DutyType.id).where(DutyType.active.is_(True))).scalars().all()
    )
    full_coverage_etids: set[uuid.UUID] = set()
    if active_dt_ids:
        full_coverage_etids = {
            etid for etid, dts in etid_to_dtids.items() if active_dt_ids <= dts
        }

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

        result.append(
            SoldierInput(
                id=s.id,
                enrolled_at=s.enrolled_at,
                cumulative_score=cum,
                active_days=ad,
                hierarchy_node_id=s.hierarchy_node_id,
                approved_constraint_dates=soldier_constraints.get(s.id, []),
                exempted_duty_type_ids=soldier_exempt_dtype_ids.get(s.id, set()),
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
    reserves: list[ReserveEntry],
    duty_blocks: list,
    soldier_names: dict[uuid.UUID, str],
    actor_id: uuid.UUID | None,
) -> None:
    """Insert algorithm_draft assignments, explanations, and reserve rows."""
    duty_map = {d.id: d for d in duty_blocks}
    explanation_map = {e.duty_id: e for e in explanation_data.per_assignment}
    reserve_map: dict[uuid.UUID, uuid.UUID] = {
        e.duty_id: e.reserve_soldier_id for e in reserves
    }

    for a in result.assignments:
        block: DutyBlock = duty_map[a.duty_id]
        da = DutyAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=block.duty_type_id,
            duty_location_id=block.duty_location_id,
            start_date=block.start_date,
            end_date=block.end_date,
            status="algorithm_draft",
            created_by=actor_id,
            notes=None,
        )
        session.add(da)
        session.flush()  # populate da.id

        exp = explanation_map.get(a.duty_id)
        if exp is not None:
            payload = _explanation_payload(
                exp,
                dm_view=True,
                soldier_names=soldier_names,
            )
            payload["global_before"] = explanation_data.global_metrics_before
            payload["global_after"] = explanation_data.global_metrics_after

            session.add(
                AssignmentExplanation(
                    duty_assignment_id=da.id,
                    payload=payload,
                    algorithm_version=explanation_data.algorithm_version,
                    solver_seed=str(explanation_data.solver_seed),
                )
            )

        reserve_soldier_id = reserve_map.get(a.duty_id)
        if reserve_soldier_id is not None:
            session.add(
                ReserveAssignment(
                    duty_assignment_id=da.id,
                    reserve_soldier_id=reserve_soldier_id,
                    reason="auto: nearest in hierarchy",
                )
            )

        write_audit(
            session,
            actor_id=actor_id,
            action="algorithm.proposal.create",
            entity_type="duty_assignment",
            entity_id=da.id,
            after={"status": "algorithm_draft", "job_id": str(job.id)},
        )


def run_algorithm_job(job_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    """Background task: load data, run solver, persist results."""
    from app.algorithm.explain import build_explanations
    from app.algorithm.reserve import select_reserves
    from app.algorithm.solver import solve
    from app.db.session import session_scope

    with session_scope() as session:
        job = session.get(AlgorithmJob, job_id)
        if job is None:
            return

        job.status = "running"
        job.started_at = datetime.now(tz=timezone.utc)
        session.commit()

        try:
            settings = SolverSettings(
                K=Decimal(str(job.settings_json.get("K", 8))),
                T=int(job.settings_json.get("T", 7)),
                W=int(job.settings_json.get("W", 14)),
                alpha=Decimal(str(job.settings_json.get("alpha", 1.0))),
                beta=Decimal(str(job.settings_json.get("beta", 2.0))),
                time_limit_seconds=int(job.settings_json.get("time_limit_seconds", 30)),
            )
            duty_type_ids = [uuid.UUID(s) for s in job.duty_type_ids]

            as_of = job.planning_start
            soldiers = load_soldier_inputs(session, as_of=as_of)
            duties = load_duty_blocks(
                session,
                planning_start=job.planning_start,
                planning_end=job.planning_end,
                duty_type_ids=duty_type_ids,
                duty_location_id=job.duty_location_id,
            )
            existing = load_existing_assignments(
                session,
                planning_start=job.planning_start,
                planning_end=job.planning_end,
                W=settings.W,
            )

            if not soldiers or not duties:
                job.status = "failed"
                job.error_message = "no_soldiers_or_duties"
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            result = solve(soldiers, duties, existing, settings)

            if result.status == "INFEASIBLE":
                job.status = "failed"
                job.error_message = json.dumps({"relaxed": result.relaxed, "status": "INFEASIBLE"})
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            explanation_data = build_explanations(
                soldiers=soldiers,
                duties=duties,
                assignments=result.assignments,
                solver_seed=result.seed,
                existing=existing,
            )
            hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)
            reserves = select_reserves(
                soldiers=soldiers,
                duties=duties,
                assignments=result.assignments,
                hierarchy_parent=hier_parent,
                hierarchy_children=hier_children,
                soldier_node=soldier_node,
                node_soldiers=node_soldiers,
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
                reserves=reserves,
                duty_blocks=duties,
                soldier_names=soldier_names,
                actor_id=actor_id,
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
