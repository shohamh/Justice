from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import (
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
)
from app.db.models import (
    DutyAssignment,
    DutyType,
    ExemptionDutyTypeMap,
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

    # Build exemption type → duty type ids map
    etid_to_dtids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        etid_to_dtids.setdefault(etid, set()).add(dtid)

    # Active exemptions per soldier (active as of the given date)
    active_exemptions = (
        session.execute(
            select(SoldierExemption).where(
                SoldierExemption.start_date <= as_of,
                (SoldierExemption.end_date >= as_of) | (SoldierExemption.end_date.is_(None)),
            )
        )
        .scalars()
        .all()
    )
    soldier_exempt_dtype_ids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for ex in active_exemptions:
        dtids = etid_to_dtids.get(ex.exemption_type_id, set())
        soldier_exempt_dtype_ids.setdefault(ex.soldier_id, set()).update(dtids)

    # Approved personal constraints per soldier
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
        ad = scoring_svc.active_days(session, soldier=s)
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
