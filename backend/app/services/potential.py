from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import date

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    PotentialModifier,
    Soldier,
    SoldierExemption,
)
from app.services.eligibility import DutyTypeRequirements, inferred_service_type


@dataclass
class ExemptionSummary:
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None


@dataclass
class SoldierPotentialDetail:
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None  # populated when counted is False
    exemption_names: list[str] = field(default_factory=list)  # populated when reason == "exempted"
    rank: str | None = None
    partial_exemption_names: list[str] = field(default_factory=list)  # populated when counted is True but partially exempt
    exemptions: list[ExemptionSummary] = field(default_factory=list)


@dataclass
class ModifierDetail:
    id: uuid.UUID
    delta: int
    reason: str
    start_date: date
    end_date: date | None
    created_by: uuid.UUID | None


@dataclass
class PotentialResult:
    node_id: uuid.UUID
    as_of: date
    raw_eligible_count: int
    total_soldiers: int = 0
    modifiers: list[ModifierDetail] = field(default_factory=list)
    final_potential: int = 0
    soldiers: list[SoldierPotentialDetail] = field(default_factory=list)
    partial_exemption_count: int = 0


def _rank_as_of(soldier: Soldier, reference_date: date) -> str | None:
    """Resolve the soldier's rank as of reference_date, applying next_rank_date if reached."""
    if soldier.rank is None:
        return None
    if soldier.next_rank_date is not None and soldier.next_rank_date <= reference_date:
        from app.services.eligibility import ENLISTED_RANKS, OFFICER_RANKS
        for track in (ENLISTED_RANKS, OFFICER_RANKS):
            if soldier.rank in track:
                idx = track.index(soldier.rank)
                if idx + 1 < len(track):
                    return track[idx + 1]
                return soldier.rank
        return soldier.rank
    return soldier.rank


def _base_eligible_duty_types(
    soldier: Soldier, rank: str | None, duty_types: list[DutyType], reference_date: date,
) -> set[uuid.UUID]:
    """Duty types the soldier qualifies for by rank/gender/service-type/officer
    requirements, ignoring mitvahim/alal timing entirely (potential-specific rule)."""
    eligible: set[uuid.UUID] = set()
    for dt in duty_types:
        raw = dt.requirements or {}
        try:
            reqs = DutyTypeRequirements.model_validate(raw)
        except Exception:
            eligible.add(dt.id)
            continue
        if reqs.allowed_genders and (not soldier.gender or soldier.gender not in reqs.allowed_genders):
            continue
        if reqs.allowed_ranks and (not rank or rank not in reqs.allowed_ranks):
            continue
        if reqs.allowed_service_types:
            stype = inferred_service_type(soldier, reference_date)
            if not stype or stype not in reqs.allowed_service_types:
                continue
        if not reqs.officers_allowed and soldier.is_officer:
            continue
        if not reqs.enlisted_allowed and not soldier.is_officer:
            continue
        if reqs.requires_bahad1 and not soldier.bahad1_graduate:
            continue
        eligible.add(dt.id)
    return eligible


def compute_potential(session: Session, *, node_id: uuid.UUID, reference_date: date) -> PotentialResult:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise ValueError("hierarchy_node_not_found")

    subtree_node_ids = list(
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_id))
        ).scalars().all()
    )
    subtree_soldiers = list(
        session.execute(
            select(Soldier).where(Soldier.hierarchy_node_id.in_(subtree_node_ids))
        ).scalars().all()
    )

    duty_types = list(session.execute(select(DutyType).where(DutyType.active.is_(True))).scalars().all())
    active_dt_ids = {dt.id for dt in duty_types}

    etid_to_dtids: dict[uuid.UUID, set[uuid.UUID]] = {}
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        etid_to_dtids.setdefault(etid, set()).add(dtid)
    regular_types = {
        et.id: et for et in session.execute(
            select(ExemptionType).where(ExemptionType.is_commander_exemption.is_(False))
        ).scalars().all()
    }
    for et in regular_types.values():
        if et.is_global:
            etid_to_dtids[et.id] = set(active_dt_ids)

    exemptions_by_soldier: dict[uuid.UUID, list[SoldierExemption]] = {}
    subtree_soldier_ids = [s.id for s in subtree_soldiers]
    for ex in session.execute(
        select(SoldierExemption).where(SoldierExemption.soldier_id.in_(subtree_soldier_ids))
    ).scalars().all():
        if ex.exemption_type_id in regular_types:
            exemptions_by_soldier.setdefault(ex.soldier_id, []).append(ex)

    details: list[SoldierPotentialDetail] = []
    raw_count = 0
    for s in subtree_soldiers:
        rank = _rank_as_of(s, reference_date)
        if s.left_at is not None and s.left_at <= reference_date:
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, False, "discharged", rank=rank,
            ))
            continue
        base_eligible = _base_eligible_duty_types(s, rank, duty_types, reference_date)
        active_exemptions = [
            ex for ex in exemptions_by_soldier.get(s.id, [])
            if ex.revoked_at is None
            and ex.start_date <= reference_date
            and (ex.end_date is None or ex.end_date >= reference_date)
        ]
        excluded: set[uuid.UUID] = set()
        for ex in active_exemptions:
            excluded |= etid_to_dtids.get(ex.exemption_type_id, set())
        remaining = base_eligible - excluded
        if remaining:
            partial_names: list[str] = []
            partial_items: list[ExemptionSummary] = []
            if excluded & base_eligible:
                relevant = [
                    ex for ex in active_exemptions
                    if etid_to_dtids.get(ex.exemption_type_id, set()) & base_eligible
                ]
                partial_names = sorted({regular_types[ex.exemption_type_id].name for ex in relevant})
                partial_items = [
                    ExemptionSummary(
                        id=ex.id,
                        exemption_type_name=regular_types[ex.exemption_type_id].name,
                        is_global=regular_types[ex.exemption_type_id].is_global,
                        start_date=ex.start_date,
                        end_date=ex.end_date,
                    )
                    for ex in relevant
                ]
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, True, rank=rank, partial_exemption_names=partial_names,
                exemptions=partial_items,
            ))
            raw_count += 1
        elif base_eligible:
            # would have been eligible, but active exemptions excluded every remaining duty type
            relevant = [
                ex for ex in active_exemptions
                if etid_to_dtids.get(ex.exemption_type_id, set()) & base_eligible
            ]
            names = sorted({regular_types[ex.exemption_type_id].name for ex in relevant})
            items = [
                ExemptionSummary(
                    id=ex.id,
                    exemption_type_name=regular_types[ex.exemption_type_id].name,
                    is_global=regular_types[ex.exemption_type_id].is_global,
                    start_date=ex.start_date,
                    end_date=ex.end_date,
                )
                for ex in relevant
            ]
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, False, "exempted", names, rank=rank, exemptions=items,
            ))
        else:
            details.append(SoldierPotentialDetail(
                s.id, s.full_name, False, "no_eligible_duty_types", rank=rank,
            ))

    modifier_rows = session.execute(
        select(PotentialModifier).where(
            PotentialModifier.hierarchy_node_id.in_(subtree_node_ids)
        )
    ).scalars().all()
    active_modifiers = [
        m for m in modifier_rows
        if m.start_date <= reference_date and (m.end_date is None or m.end_date >= reference_date)
    ]
    modifier_details = [
        ModifierDetail(m.id, m.delta, m.reason, m.start_date, m.end_date, m.created_by)
        for m in active_modifiers
    ]
    modifier_sum = sum(m.delta for m in active_modifiers)

    total_soldiers = sum(
        1 for s in subtree_soldiers
        if s.left_at is None or s.left_at > reference_date
    )

    return PotentialResult(
        node_id=node_id,
        as_of=reference_date,
        raw_eligible_count=raw_count,
        total_soldiers=total_soldiers,
        modifiers=modifier_details,
        final_potential=raw_count + modifier_sum,
        soldiers=details,
        partial_exemption_count=sum(1 for d in details if d.partial_exemption_names),
    )


class PotentialModifierError(Exception):
    """Raised on an invalid potential-modifier operation."""


def create_modifier(
    session: Session,
    *,
    hierarchy_node_id: uuid.UUID,
    delta: int,
    reason: str,
    start_date: date,
    end_date: date | None = None,
    actor_id: uuid.UUID | None = None,
) -> PotentialModifier:
    if session.get(HierarchyNode, hierarchy_node_id) is None:
        raise PotentialModifierError("hierarchy_node_not_found")
    if not reason or not reason.strip():
        raise PotentialModifierError("reason_required")
    if end_date is not None and end_date < start_date:
        raise PotentialModifierError("end_date_before_start_date")
    m = PotentialModifier(
        hierarchy_node_id=hierarchy_node_id,
        delta=delta,
        reason=reason,
        start_date=start_date,
        end_date=end_date,
        created_by=actor_id,
    )
    session.add(m)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="potential_modifier.create",
        entity_type="potential_modifier",
        entity_id=m.id,
        after={
            "hierarchy_node_id": str(hierarchy_node_id),
            "delta": delta,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat() if end_date else None,
        },
        context={"reason": reason},
    )
    return m


def list_modifiers(session: Session, *, hierarchy_node_id: uuid.UUID) -> list[PotentialModifier]:
    return list(
        session.execute(
            select(PotentialModifier)
            .where(PotentialModifier.hierarchy_node_id == hierarchy_node_id)
            .order_by(PotentialModifier.created_at)
        ).scalars().all()
    )


def delete_modifier(session: Session, *, modifier_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> None:
    m = session.get(PotentialModifier, modifier_id)
    if m is None:
        raise PotentialModifierError("modifier_not_found")
    before = {"hierarchy_node_id": str(m.hierarchy_node_id), "delta": m.delta, "reason": m.reason}
    session.delete(m)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="potential_modifier.delete",
        entity_type="potential_modifier",
        entity_id=modifier_id,
        before=before,
    )


def export_potential_table_xlsx(session: Session, *, root_node_id: uuid.UUID, reference_date: date) -> bytes:
    """Build an .xlsx snapshot of root_node_id and all its descendant nodes' potential."""
    root = session.get(HierarchyNode, root_node_id)
    if root is None:
        raise ValueError("hierarchy_node_not_found")
    subtree = list(
        session.execute(
            select(HierarchyNode).where(HierarchyNode.path_ids.any(root_node_id))
        ).scalars().all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Potential"
    ws.append(["Node", "Level", "Raw Eligible", "Modifiers Sum", "Final Potential", "As Of"])
    for n in subtree:
        r = compute_potential(session, node_id=n.id, reference_date=reference_date)
        mod_sum = sum(m.delta for m in r.modifiers)
        ws.append([n.name, n.level, r.raw_eligible_count, mod_sum, r.final_potential, reference_date.isoformat()])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
