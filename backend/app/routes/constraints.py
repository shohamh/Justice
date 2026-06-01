from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, PersonalConstraint, Soldier
from app.db.session import get_session
from app.services import constraints as svc

router = APIRouter(tags=["constraints"])


# ── Schemas ──


class ConstraintOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str
    status: str
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime


class SubmitRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str = Field(max_length=1000)


class ApproveRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)


class RejectRequest(BaseModel):
    decision_note: str = Field(max_length=1000)


class PendingCountOut(BaseModel):
    count: int


# ── Helpers ──


def _out(c: PersonalConstraint) -> ConstraintOut:
    return ConstraintOut(
        id=c.id,
        soldier_id=c.soldier_id,
        start_date=c.start_date,
        end_date=c.end_date,
        reason=c.reason,
        status=c.status,
        decided_by=c.decided_by,
        decided_at=c.decided_at,
        decision_note=c.decision_note,
        created_at=c.created_at,
    )


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


# ── Self-service ──


@router.get("/me/constraints", response_model=list[ConstraintOut])
def list_own(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ConstraintOut]:
    return [_out(c) for c in svc.list_constraints(session, soldier_id=user.id)]


@router.post("/me/constraints", response_model=ConstraintOut, status_code=status.HTTP_201_CREATED)
def submit(
    body: SubmitRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ConstraintOut:
    try:
        c = svc.submit_constraint(
            session,
            soldier_id=user.id,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            actor_id=user.id,
        )
    except svc.ConstraintError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(c)
    return _out(c)


@router.delete("/me/constraints/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def cancel(
    constraint_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None or c.soldier_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    svc.cancel_constraint(session, constraint_id=constraint_id, actor_id=user.id)
    session.commit()


# ── Cross-soldier view ──


@router.get("/soldiers/{soldier_id}/constraints", response_model=list[ConstraintOut])
def list_for_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ConstraintOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.CONSTRAINT_READ, target_node=_node_of(session, s))
    return [_out(c) for c in svc.list_constraints(session, soldier_id=soldier_id)]


# ── Approval management ──


@router.get("/constraints/pending", response_model=list[ConstraintOut])
def pending_list(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ConstraintOut]:
    roots = scope_root_ids(session, user)
    if user.role != "admin" and not roots:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    if user.role == "admin":
        rows = list(
            session.execute(
                select(PersonalConstraint)
                .where(PersonalConstraint.status == "pending")
                .order_by(PersonalConstraint.created_at.asc())
            )
            .scalars()
            .all()
        )
        return [_out(c) for c in rows]
    return [_out(c) for c in svc.list_pending_approvals(session, node_ids=roots)]


@router.get("/constraints/pending/count", response_model=PendingCountOut)
def pending_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PendingCountOut:
    roots = scope_root_ids(session, user)
    if user.role != "admin" and not roots:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    if user.role == "admin":
        cnt = len(
            list(
                session.execute(
                    select(PersonalConstraint).where(PersonalConstraint.status == "pending")
                )
                .scalars()
                .all()
            )
        )
        return PendingCountOut(count=cnt)
    if not roots:
        return PendingCountOut(count=0)
    return PendingCountOut(count=svc.pending_approval_count(session, node_ids=roots))


@router.post("/constraints/{constraint_id}/approve", response_model=ConstraintOut)
def approve(
    constraint_id: uuid.UUID,
    body: ApproveRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ConstraintOut:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    s = _load_soldier(session, c.soldier_id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=_node_of(session, s))
    try:
        c = svc.approve_constraint(
            session, constraint_id=constraint_id, actor_id=user.id, decision_note=body.decision_note
        )
    except svc.ConstraintError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(c)
    return _out(c)


@router.post("/constraints/{constraint_id}/reject", response_model=ConstraintOut)
def reject(
    constraint_id: uuid.UUID,
    body: RejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ConstraintOut:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    s = _load_soldier(session, c.soldier_id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=_node_of(session, s))
    try:
        c = svc.reject_constraint(
            session, constraint_id=constraint_id, actor_id=user.id, decision_note=body.decision_note
        )
    except svc.ConstraintError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(c)
    return _out(c)
