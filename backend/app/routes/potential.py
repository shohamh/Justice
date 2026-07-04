from __future__ import annotations

import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, can_see_private_node
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, PotentialModifier, Soldier
from app.db.session import get_session
from app.services import potential as svc

router = APIRouter(prefix="/potential", tags=["potential"])


class SoldierDetailOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None
    exemption_names: list[str] | None = None
    rank: str | None = None


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
            )
            for s in r.soldiers
        ],
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


@router.delete("/modifiers/{modifier_id}", status_code=status.HTTP_204_NO_CONTENT)
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
