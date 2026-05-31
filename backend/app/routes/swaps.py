from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import SwapRequest, Soldier
from app.db.session import get_session
from app.services import swaps as svc

router = APIRouter(tags=["swaps"])


class SwapOut(BaseModel):
    id: uuid.UUID
    duty_assignment_id: uuid.UUID
    duty_date: date
    requesting_soldier_id: uuid.UUID
    target_soldier_id: uuid.UUID | None
    covering_soldier_id: uuid.UUID | None
    status: str
    reason: str | None
    requester_side_approved: bool | None
    covering_side_approved: bool | None
    decision_note: str | None
    created_at: datetime


class CreateSwapRequest(BaseModel):
    duty_assignment_id: uuid.UUID
    duty_date: date
    target_soldier_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ClaimRequest(BaseModel):
    pass


class ApproveSideRequest(BaseModel):
    side: str  # "requester" | "covering"


class RejectRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)


def _out(r: SwapRequest) -> SwapOut:
    return SwapOut(
        id=r.id, duty_assignment_id=r.duty_assignment_id, duty_date=r.duty_date,
        requesting_soldier_id=r.requesting_soldier_id, target_soldier_id=r.target_soldier_id,
        covering_soldier_id=r.covering_soldier_id, status=r.status, reason=r.reason,
        requester_side_approved=r.requester_side_approved,
        covering_side_approved=r.covering_side_approved,
        decision_note=r.decision_note, created_at=r.created_at,
    )


def _err(exc: svc.SwapError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/me/swaps", response_model=list[SwapOut])
def my_swaps(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    return [_out(r) for r in svc.list_own(session, soldier_id=user.id)]


@router.get("/swaps/board", response_model=list[SwapOut])
def board(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    return [_out(r) for r in svc.list_open_board(session, for_soldier_id=user.id)]


@router.post("/me/swaps", response_model=SwapOut, status_code=status.HTTP_201_CREATED)
def create(
    body: CreateSwapRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        r = svc.create_request(
            session, requesting_soldier_id=user.id, duty_assignment_id=body.duty_assignment_id,
            duty_date=body.duty_date, target_soldier_id=body.target_soldier_id,
            reason=body.reason, actor_id=user.id,
        )
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r)


@router.post("/swaps/{request_id}/claim", response_model=SwapOut)
def claim(
    request_id: uuid.UUID,
    _body: ClaimRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        r = svc.claim_request(session, request_id=request_id, covering_soldier_id=user.id, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r)


@router.delete("/me/swaps/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    r = session.get(SwapRequest, request_id)
    if r is None or r.requesting_soldier_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.cancel_request(session, request_id=request_id, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()


@router.get("/swaps/pending", response_model=list[SwapOut])
def pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    roots = scope_root_ids(session, user)
    if user.role != "admin" and not roots:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return [_out(r) for r in svc.list_pending_approval(session)]


@router.post("/swaps/{request_id}/approve", response_model=SwapOut)
def approve(
    request_id: uuid.UUID,
    body: ApproveSideRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    authorize(session, user, Action.SWAP_APPROVE, target_node=None)
    try:
        r = svc.approve_side(session, request_id=request_id, side=body.side, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r)


@router.post("/swaps/{request_id}/reject", response_model=SwapOut)
def reject(
    request_id: uuid.UUID,
    body: RejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    authorize(session, user, Action.SWAP_APPROVE, target_node=None)
    try:
        r = svc.reject_request(session, request_id=request_id, decision_note=body.decision_note, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r)
