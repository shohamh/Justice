from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier, SoldierEnrollmentRequest
from app.db.session import get_session
from app.services import enrollment as svc

router = APIRouter(prefix="/enrollment-requests", tags=["enrollment"])


class EnrollmentRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str
    requested_node_id: uuid.UUID
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None


class DecisionBody(BaseModel):
    decision_note: str | None = None


@router.get("/pending", response_model=list[EnrollmentRequestOut])
def list_pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EnrollmentRequestOut]:
    if user.role == "admin":
        reqs = session.execute(
            select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.status == "pending")
        ).scalars().all()
    else:
        roots = scope_root_ids(session, user)
        reqs = svc.list_pending_for_node_ids(session, roots)
    soldier_ids = {r.soldier_id for r in reqs}
    soldiers = {
        s.id: s
        for s in session.execute(
            select(Soldier).where(Soldier.id.in_(soldier_ids))
        ).scalars().all()
    }
    return [
        EnrollmentRequestOut(
            id=r.id, soldier_id=r.soldier_id,
            soldier_name=soldiers[r.soldier_id].full_name if r.soldier_id in soldiers else str(r.soldier_id)[:8],
            requested_node_id=r.requested_node_id,
            status=r.status, decided_by=r.decided_by, decision_note=r.decision_note,
        )
        for r in reqs
    ]


@router.post("/{request_id}/approve")
def approve(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    try:
        svc.approve_enrollment(session, request_id=request_id, decider_id=user.id, decision_note=body.decision_note)
        session.commit()
        return {"status": "ok"}
    except svc.EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{request_id}/reject")
def reject(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not body.decision_note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="decision_note required")
    target_node = session.get(HierarchyNode, req.requested_node_id)
    authorize(session, user, Action.ENROLLMENT_APPROVE, target_node=target_node)
    try:
        svc.reject_enrollment(session, request_id=request_id, decider_id=user.id, decision_note=body.decision_note)
        session.commit()
        return {"status": "ok"}
    except svc.EnrollmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
