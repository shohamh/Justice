from __future__ import annotations

import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import (
    Action,
    authorize,
    can_see_private_node,
    is_commander,
    is_duty_manager,
    scope_root_ids,
)
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, PotentialModifier, Soldier
from app.db.session import get_session
from app.services import potential as svc
from app.services.node_effort_potential import compute_node_effort_potential

router = APIRouter(prefix="/potential", tags=["potential"])


class ExemptionSummaryItemOut(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None


class SoldierDetailOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None
    exemption_names: list[str] | None = None
    rank: str | None = None
    partial_exemption_names: list[str] | None = None
    exemptions: list[ExemptionSummaryItemOut] | None = None


class ModifierOut(BaseModel):
    id: uuid.UUID
    delta: int
    reason: str
    start_date: str
    end_date: str | None
    created_by: uuid.UUID | None


class PotentialOut(BaseModel):
    node_id: uuid.UUID
    as_of: str
    raw_eligible_count: int
    total_soldiers: int
    modifiers: list[ModifierOut]
    final_potential: int
    soldiers: list[SoldierDetailOut]
    partial_exemption_count: int


def _out(r: svc.PotentialResult, *, can_view_exemptions: bool) -> PotentialOut:
    return PotentialOut(
        node_id=r.node_id,
        as_of=r.as_of.isoformat(),
        raw_eligible_count=r.raw_eligible_count,
        total_soldiers=r.total_soldiers,
        modifiers=[
            ModifierOut(
                id=m.id, delta=m.delta, reason=m.reason,
                start_date=m.start_date.isoformat(),
                end_date=m.end_date.isoformat() if m.end_date else None,
                created_by=m.created_by,
            ) for m in r.modifiers
        ],
        final_potential=r.final_potential,
        soldiers=[
            SoldierDetailOut(
                soldier_id=s.soldier_id, full_name=s.full_name, counted=s.counted, reason=s.reason,
                exemption_names=(s.exemption_names or None) if can_view_exemptions else None,
                rank=s.rank,
                partial_exemption_names=(s.partial_exemption_names or None) if can_view_exemptions else None,
                exemptions=(
                    [
                        ExemptionSummaryItemOut(
                            id=e.id, exemption_type_name=e.exemption_type_name,
                            is_global=e.is_global, start_date=e.start_date, end_date=e.end_date,
                        )
                        for e in s.exemptions
                    ]
                    if can_view_exemptions else None
                ),
            )
            for s in r.soldiers
        ],
        partial_exemption_count=r.partial_exemption_count,
    )


def _can_view_exemptions(session: Session, user: Soldier, node: HierarchyNode) -> bool:
    return can_see_private_node(session, user, node)


@router.get("", response_model=PotentialOut)
def get_potential(
    node_id: uuid.UUID,
    reference_date: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PotentialOut:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.POTENTIAL_READ, target_node=node)
    ref = date.fromisoformat(reference_date) if reference_date else date.today()
    result = svc.compute_potential(session, node_id=node_id, reference_date=ref)
    return _out(result, can_view_exemptions=_can_view_exemptions(session, user, node))


class NodeEffortPotentialOut(BaseModel):
    node_id: uuid.UUID
    node_name: str
    final_potential: int
    total_effort: float
    sibling_potential_share: float | None
    sibling_effort_share: float | None
    sibling_gap: float | None
    global_potential_share: float | None
    global_effort_share: float | None
    global_gap: float | None


class EffortGapOut(BaseModel):
    nodes: list[NodeEffortPotentialOut]


@router.get("/effort-gap", response_model=EffortGapOut)
def get_effort_gap(
    reference_date: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> EffortGapOut:
    is_admin = user.role == "admin"
    if not is_admin and not is_commander(session, user.id) and not is_duty_manager(session, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    ref = date.fromisoformat(reference_date) if reference_date else date.today()
    results = compute_node_effort_potential(session, reference_date=ref)

    if is_admin:
        allowed_node_ids = None
    else:
        roots = scope_root_ids(session, user)
        nodes_by_id = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
        allowed_node_ids = {
            node_id
            for node_id, node in nodes_by_id.items()
            if any(root in node.path_ids for root in roots)
        }

    return EffortGapOut(
        nodes=[
            NodeEffortPotentialOut(
                node_id=r.node_id,
                node_name=r.node_name,
                final_potential=r.final_potential,
                total_effort=r.total_effort,
                sibling_potential_share=r.sibling_potential_share,
                sibling_effort_share=r.sibling_effort_share,
                sibling_gap=r.sibling_gap,
                global_potential_share=r.global_potential_share,
                global_effort_share=r.global_effort_share,
                global_gap=r.global_gap,
            )
            for r in results.values()
            if allowed_node_ids is None or r.node_id in allowed_node_ids
        ]
    )


class ModifierCreateIn(BaseModel):
    hierarchy_node_id: uuid.UUID
    delta: int
    reason: str
    start_date: str
    end_date: str | None = None


@router.get("/modifiers", response_model=list[ModifierOut])
def get_modifiers(
    hierarchy_node_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ModifierOut]:
    node = session.get(HierarchyNode, hierarchy_node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.POTENTIAL_READ, target_node=node)
    rows = svc.list_modifiers(session, hierarchy_node_id=hierarchy_node_id)
    return [
        ModifierOut(
            id=m.id, delta=m.delta, reason=m.reason,
            start_date=m.start_date.isoformat(),
            end_date=m.end_date.isoformat() if m.end_date else None,
            created_by=m.created_by,
        ) for m in rows
    ]


@router.post("/modifiers", response_model=ModifierOut, status_code=status.HTTP_201_CREATED)
def create_modifier_route(
    body: ModifierCreateIn,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ModifierOut:
    node = session.get(HierarchyNode, body.hierarchy_node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.POTENTIAL_MODIFIER_MANAGE, target_node=node)
    try:
        m = svc.create_modifier(
            session,
            hierarchy_node_id=body.hierarchy_node_id,
            delta=body.delta,
            reason=body.reason,
            start_date=date.fromisoformat(body.start_date),
            end_date=date.fromisoformat(body.end_date) if body.end_date else None,
            actor_id=user.id,
        )
    except svc.PotentialModifierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return ModifierOut(
        id=m.id, delta=m.delta, reason=m.reason,
        start_date=m.start_date.isoformat(),
        end_date=m.end_date.isoformat() if m.end_date else None,
        created_by=m.created_by,
    )


@router.delete("/modifiers/{modifier_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_modifier_route(
    modifier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    m = session.get(PotentialModifier, modifier_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    node = session.get(HierarchyNode, m.hierarchy_node_id)
    authorize(session, user, Action.POTENTIAL_MODIFIER_MANAGE, target_node=node)
    svc.delete_modifier(session, modifier_id=modifier_id, actor_id=user.id)
    session.commit()


@router.get("/export")
def export_potential(
    node_id: uuid.UUID,
    reference_date: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> StreamingResponse:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.POTENTIAL_READ, target_node=node)
    ref = date.fromisoformat(reference_date) if reference_date else date.today()
    content = svc.export_potential_table_xlsx(session, root_node_id=node_id, reference_date=ref)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="potential_{ref.isoformat()}.xlsx"'},
    )
