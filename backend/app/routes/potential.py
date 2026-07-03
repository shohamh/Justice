from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import potential as svc

router = APIRouter(prefix="/potential", tags=["potential"])


class SoldierDetailOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    counted: bool
    reason: str | None = None


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
    modifiers: list[ModifierOut]
    final_potential: int
    soldiers: list[SoldierDetailOut]


def _out(r: svc.PotentialResult) -> PotentialOut:
    return PotentialOut(
        node_id=r.node_id,
        as_of=r.as_of.isoformat(),
        raw_eligible_count=r.raw_eligible_count,
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
            SoldierDetailOut(soldier_id=s.soldier_id, full_name=s.full_name, counted=s.counted, reason=s.reason)
            for s in r.soldiers
        ],
    )


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
    return _out(result)
