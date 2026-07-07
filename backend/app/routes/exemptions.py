from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, can_see_private, is_commander, is_duty_manager
from app.auth.deps import require_password_changed
from app.db.models import ExemptionType, HierarchyNode, Soldier, SoldierExemption
from app.db.session import get_session
from app.services import exemptions as svc
from app.services.authority import commander_can_grant_commander_exemption

router = APIRouter(prefix="/soldiers/{soldier_id}/exemptions", tags=["exemptions"])


class ExemptionOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    exemption_type_id: uuid.UUID | None
    start_date: date
    end_date: date | None
    reason: str | None
    granted_by: uuid.UUID | None
    revoke_reason: str | None
    revoked_by_name: str | None


class ExemptionDetailOut(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None
    reason: str | None
    granted_by_name: str | None
    revoke_reason: str | None
    revoked_by_name: str | None


class GrantRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)


def _out(session: Session, ex: SoldierExemption, include_sensitive: bool = True) -> ExemptionOut:
    revoked_by_name = None
    if include_sensitive and ex.revoked_by is not None:
        revoker = session.get(Soldier, ex.revoked_by)
        revoked_by_name = revoker.full_name if revoker else None
    return ExemptionOut(
        id=ex.id,
        soldier_id=ex.soldier_id,
        exemption_type_id=ex.exemption_type_id if include_sensitive else None,
        start_date=ex.start_date,
        end_date=ex.end_date,
        reason=ex.reason if include_sensitive else None,
        granted_by=ex.granted_by,
        revoke_reason=ex.revoke_reason if include_sensitive else None,
        revoked_by_name=revoked_by_name,
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
    include_sensitive = can_see_private(session, user, s)
    return [
        _out(session, ex, include_sensitive=include_sensitive)
        for ex in svc.list_exemptions(session, soldier_id=soldier_id)
    ]


@router.get("/{exemption_id}", response_model=ExemptionDetailOut)
def get_detail(
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionDetailOut:
    s = _load_soldier(session, soldier_id)
    ex = session.get(SoldierExemption, exemption_id)
    if ex is None or ex.soldier_id != soldier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        authorize(session, user, Action.EXEMPTION_READ, target_node=_node_of(session, s))
    ex_type = session.get(ExemptionType, ex.exemption_type_id) if ex.exemption_type_id else None
    include_sensitive = can_see_private(session, user, s)
    granted_by_name = None
    if ex.granted_by is not None:
        granter = session.get(Soldier, ex.granted_by)
        granted_by_name = granter.full_name if granter else None
    revoked_by_name = None
    if include_sensitive and ex.revoked_by is not None:
        revoker = session.get(Soldier, ex.revoked_by)
        revoked_by_name = revoker.full_name if revoker else None
    return ExemptionDetailOut(
        id=ex.id,
        exemption_type_name=ex_type.name if ex_type else "—",
        is_global=ex_type.is_global if ex_type else False,
        start_date=ex.start_date,
        end_date=ex.end_date,
        reason=ex.reason if include_sensitive else None,
        granted_by_name=granted_by_name,
        revoke_reason=ex.revoke_reason if include_sensitive else None,
        revoked_by_name=revoked_by_name,
    )


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
    return _out(session, ex, include_sensitive=True)


class GrantCommanderExemptionRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/commander-exemption", response_model=ExemptionOut, status_code=status.HTTP_201_CREATED)
def grant_commander_exemption_route(
    soldier_id: uuid.UUID,
    body: GrantCommanderExemptionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionOut:
    s = _load_soldier(session, soldier_id)
    target_node = _node_of(session, s)

    allowed = user.role == "admin"
    if not allowed and is_duty_manager(session, user.id):
        from app.auth.authz import _node_in_scope, scope_root_ids
        allowed = _node_in_scope(target_node, scope_root_ids(session, user))
    if not allowed and is_commander(session, user.id):
        from app.auth.authz import _node_in_scope, scope_root_ids
        in_scope = _node_in_scope(target_node, scope_root_ids(session, user))
        allowed = in_scope and commander_can_grant_commander_exemption(
            session, commander_id=user.id, commander_rank=user.rank,
        )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    try:
        ex = svc.grant_commander_exemption(
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
    return _out(session, ex, include_sensitive=True)


class RevokeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@router.delete("/{exemption_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def revoke(
    soldier_id: uuid.UUID,
    exemption_id: uuid.UUID,
    body: RevokeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    s = _load_soldier(session, soldier_id)
    authorize(session, user, Action.EXEMPTION_GRANT, target_node=_node_of(session, s))
    ex = session.get(SoldierExemption, exemption_id)
    if ex is None or ex.soldier_id != soldier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    svc.revoke_exemption(session, exemption_id=exemption_id, reason=body.reason, actor_id=user.id)
    session.commit()
