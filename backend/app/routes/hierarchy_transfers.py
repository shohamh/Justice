from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, forbid_self_target
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, HierarchyTransferRequest, Soldier
from app.db.session import get_session
from app.services import hierarchy_transfers as svc

router = APIRouter(prefix="/hierarchy-transfers", tags=["hierarchy_transfers"])


class CreateTransferBody(BaseModel):
    soldier_id: uuid.UUID
    to_node_id: uuid.UUID
    reason: str | None = None


class DecisionBody(BaseModel):
    decision_note: str | None = None


class TransferOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    from_node_id: uuid.UUID | None
    to_node_id: uuid.UUID
    status: str
    reason: str | None


def _out(req: HierarchyTransferRequest, soldier_name: str) -> TransferOut:
    return TransferOut(
        id=req.id, soldier_id=req.soldier_id, soldier_name=soldier_name,
        from_node_id=req.from_node_id, to_node_id=req.to_node_id, status=req.status,
        reason=req.reason,
    )


@router.post("", response_model=TransferOut)
def create_transfer(
    body: CreateTransferBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransferOut:
    soldier = session.get(Soldier, body.soldier_id)
    if soldier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="soldier_not_found")
    source_node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    authorize(session, user, Action.HIERARCHY_TRANSFER, target_node=source_node)
    try:
        req = svc.create_request(session, soldier_id=body.soldier_id, to_node_id=body.to_node_id, requested_by=user.id, reason=body.reason)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req, soldier.full_name)


@router.post("/{request_id}/approve", response_model=TransferOut)
def approve_transfer(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransferOut:
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    forbid_self_target(user, req.soldier_id)
    soldier = session.get(Soldier, req.soldier_id)
    dest_node = session.get(HierarchyNode, req.to_node_id)
    authorize(session, user, Action.HIERARCHY_TRANSFER, target_node=dest_node)
    try:
        req = svc.approve_request(session, request_id=request_id, actor_id=user.id)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req, soldier.full_name if soldier else "")


@router.post("/{request_id}/reject", response_model=TransferOut)
def reject_transfer(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransferOut:
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    forbid_self_target(user, req.soldier_id)
    soldier = session.get(Soldier, req.soldier_id)
    dest_node = session.get(HierarchyNode, req.to_node_id)
    authorize(session, user, Action.HIERARCHY_TRANSFER, target_node=dest_node)
    try:
        req = svc.reject_request(session, request_id=request_id, actor_id=user.id, decision_note=body.decision_note)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req, soldier.full_name if soldier else "")


@router.get("/pending", response_model=list[TransferOut])
def list_pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TransferOut]:
    reqs = svc.list_pending_for_approver(session, approver_id=user.id)
    soldier_ids = {r.soldier_id for r in reqs}
    names = {
        s.id: s.full_name
        for s in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars()
    } if soldier_ids else {}
    return [_out(r, names.get(r.soldier_id, "")) for r in reqs]
