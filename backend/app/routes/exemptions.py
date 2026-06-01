from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier, SoldierExemption
from app.db.session import get_session
from app.services import exemptions as svc

router = APIRouter(prefix="/soldiers/{soldier_id}/exemptions", tags=["exemptions"])


class ExemptionOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None
    reason: str | None
    granted_by: uuid.UUID | None


class GrantRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)


def _out(ex: SoldierExemption) -> ExemptionOut:
    return ExemptionOut(
        id=ex.id,
        soldier_id=ex.soldier_id,
        exemption_type_id=ex.exemption_type_id,
        start_date=ex.start_date,
        end_date=ex.end_date,
        reason=ex.reason,
        granted_by=ex.granted_by,
    )


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


@router.get("", response_model=list[ExemptionOut])
def list_(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.EXEMPTION_READ, target_node=_node_of(session, s))
    return [_out(ex) for ex in svc.list_exemptions(session, soldier_id=soldier_id)]


@router.post("", response_model=ExemptionOut, status_code=status.HTTP_201_CREATED)
def grant(
    soldier_id: uuid.UUID,
    body: GrantRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionOut:
    s = _load_soldier(session, soldier_id)
    authorize(session, user, Action.EXEMPTION_GRANT, target_node=_node_of(session, s))
    try:
        ex = svc.grant_exemption(
            session,
            soldier_id=soldier_id,
            exemption_type_id=body.exemption_type_id,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            actor_id=user.id,
        )
    except svc.ExemptionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(ex)
    return _out(ex)


@router.delete("/{exemption_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def revoke(
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    s = _load_soldier(session, soldier_id)
    authorize(session, user, Action.EXEMPTION_GRANT, target_node=_node_of(session, s))
    ex = session.get(SoldierExemption, exemption_id)
    if ex is None or ex.soldier_id != soldier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    svc.revoke_exemption(session, exemption_id=exemption_id, actor_id=user.id)
    session.commit()
