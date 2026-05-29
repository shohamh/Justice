from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import ExemptionRequest, HierarchyNode, Soldier
from app.db.session import get_session
from app.services.exemption_requests import (
    ExemptionRequestError,
    approve_request,
    count_pending_requests,
    list_own_requests,
    list_pending_requests,
    reject_request,
    submit_request,
)

router = APIRouter(tags=["exemption-requests"])


class ExemptionRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    exemption_type_id: uuid.UUID
    start_date: str
    end_date: str | None
    reason: str | None
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: str


class CreateExemptionRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = None
    reason: str | None = None


class ApproveRejectRequest(BaseModel):
    decision_note: str | None = None


def _out(req: ExemptionRequest) -> ExemptionRequestOut:
    return ExemptionRequestOut(
        id=req.id,
        soldier_id=req.soldier_id,
        exemption_type_id=req.exemption_type_id,
        start_date=req.start_date.isoformat(),
        end_date=req.end_date.isoformat() if req.end_date else None,
        reason=req.reason,
        status=req.status,
        decided_by=req.decided_by,
        decision_note=req.decision_note,
        created_at=req.created_at.isoformat(),
    )


@router.post("/me/exemption-requests", response_model=ExemptionRequestOut, status_code=status.HTTP_201_CREATED)
def create_exemption_request(
    body: CreateExemptionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    try:
        req = submit_request(
            session,
            soldier_id=user.id,
            exemption_type_id=body.exemption_type_id,
            start_date=date.fromisoformat(body.start_date),
            end_date=date.fromisoformat(body.end_date) if body.end_date else None,
            reason=body.reason,
        )
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(req)


@router.get("/me/exemption-requests", response_model=list[ExemptionRequestOut])
def get_my_exemption_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    return [_out(r) for r in list_own_requests(session, user.id)]


@router.get("/exemption-requests/pending", response_model=list[ExemptionRequestOut])
def get_pending_exemption_requests(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    root_ids = scope_root_ids(session, user)
    if not root_ids:
        return []
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(root_ids)))
        .subquery()
    )
    soldier_ids = list(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        )
        .scalars()
        .all()
    )
    return [_out(r) for r in list_pending_requests(session, soldier_ids)]


@router.get("/exemption-requests/pending/count")
def get_pending_exemption_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    root_ids = scope_root_ids(session, user)
    if not root_ids:
        return {"count": 0}
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(root_ids)))
        .subquery()
    )
    soldier_ids = list(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        )
        .scalars()
        .all()
    )
    return {"count": count_pending_requests(session, soldier_ids)}


@router.post("/exemption-requests/{request_id}/approve", response_model=ExemptionRequestOut)
def approve_exemption_request(
    request_id: uuid.UUID,
    body: ApproveRejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    try:
        result = approve_request(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(result)


@router.post("/exemption-requests/{request_id}/reject", response_model=ExemptionRequestOut)
def reject_exemption_request(
    request_id: uuid.UUID,
    body: ApproveRejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    try:
        result = reject_request(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(result)
