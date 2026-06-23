from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids, can_see_private
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, PersonalConstraint, Soldier
from app.db.session import get_session
from app.services import constraints as svc

router = APIRouter(tags=["constraints"])


# ── Schemas ──


class ConstraintOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    start_date: date
    end_date: date
    reason: str | None          # None when viewer cannot see private field
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


def _out(c: PersonalConstraint, soldier_name: str = "", node_name: str | None = None, include_reason: bool = True) -> ConstraintOut:
    return ConstraintOut(
        id=c.id,
        soldier_id=c.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        start_date=c.start_date,
        end_date=c.end_date,
        reason=c.reason if include_reason else None,
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
    include_reason = can_see_private(session, user, s)
    return [_out(c, include_reason=include_reason) for c in svc.list_constraints(session, soldier_id=soldier_id)]


# ── Approval management ──


def _attach_names(
    session: Session, rows: list[PersonalConstraint], user: Soldier
) -> list[ConstraintOut]:
    """Bulk-load soldier and node names then build ConstraintOut list."""
    if not rows:
        return []
    soldier_ids = {c.soldier_id for c in rows}
    soldiers_by_id = {
        s.id: s
        for s in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars().all()
    }
    node_ids = {s.hierarchy_node_id for s in soldiers_by_id.values() if s.hierarchy_node_id}
    nodes_by_id = (
        {
            n.id: n
            for n in session.execute(
                select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
            ).scalars().all()
        }
        if node_ids
        else {}
    )
    result = []
    for c in rows:
        s = soldiers_by_id.get(c.soldier_id)
        soldier_name = s.full_name if s else str(c.soldier_id)[:8]
        node_name = (
            nodes_by_id[s.hierarchy_node_id].name
            if s and s.hierarchy_node_id and s.hierarchy_node_id in nodes_by_id
            else None
        )
        include_reason = s is not None and can_see_private(session, user, s)
        result.append(_out(c, soldier_name=soldier_name, node_name=node_name, include_reason=include_reason))
    return result


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
                .order_by(PersonalConstraint.start_date.asc())
            )
            .scalars()
            .all()
        )
        return _attach_names(session, rows, user)
    return _attach_names(session, svc.list_pending_approvals(session, node_ids=roots), user)


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
    return _out(c, include_reason=True)


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
    return _out(c, include_reason=True)
