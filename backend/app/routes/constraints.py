from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import (
    Action,
    authorize,
    can,
    can_see_private,
    forbid_self_target,
    is_commander,
    is_duty_manager,
    scope_root_ids,
)
from app.services.authority import request_cancellation_authorized, senior_commander_approval_authorized
from app.auth.deps import require_enrolled, require_password_changed
from app.db.models import HierarchyNode, PersonalConstraint, Soldier
from app.db.session import get_session
from app.services.holidays import HolidayHit, holidays_in_range
from app.services.request_metadata import (
    constraint_audit_latest,
    latest_activity,
    person_ref,
    waiting_on as resolve_waiting_on,
)
from app.services import constraints as svc

router = APIRouter(tags=["constraints"])


# ── Schemas ──


class NearestApproverOut(BaseModel):
    id: uuid.UUID
    name: str


class PersonRefOut(BaseModel):
    soldier_id: uuid.UUID
    name: str


class WaitingOnOut(BaseModel):
    kind: str  # "commander" | "duty_manager"
    soldier_id: uuid.UUID
    name: str


class ConstraintOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    start_date: date
    end_date: date
    reason: str | None  # None when viewer cannot see private field
    status: str
    decided_by: PersonRefOut | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime
    nearest_commander: NearestApproverOut | None = None
    nearest_duty_manager: NearestApproverOut | None = None
    can_approve: bool = True
    can_cancel: bool = False
    requested_at: datetime | None = None
    updated_at: datetime | None = None
    waiting_on: WaitingOnOut | None = None
    commander_approved_by: PersonRefOut | None = None
    crossed_holidays: list[HolidayHit] = []


class SubmitRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str = Field(max_length=1000)


class ApproveRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)


class RejectRequest(BaseModel):
    decision_note: str = Field(max_length=1000)


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class PendingCountOut(BaseModel):
    count: int


class RemainingDaysOut(BaseModel):
    cap_days: int
    used_days: int
    remaining_days: int
    period_start: date
    period_end: date


# ── Helpers ──

def _out(
    session: Session,
    c: PersonalConstraint,
    soldier_name: str = "",
    node_name: str | None = None,
    include_reason: bool = True,
    nearest_commander: NearestApproverOut | None = None,
    nearest_duty_manager: NearestApproverOut | None = None,
    can_approve: bool = True,
    can_cancel: bool = False,
    audit_times: dict[uuid.UUID, datetime] | None = None,
) -> ConstraintOut:
    crossed_holidays = holidays_in_range(c.start_date, c.end_date, end_inclusive=True)
    return ConstraintOut(
        id=c.id,
        soldier_id=c.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        start_date=c.start_date,
        end_date=c.end_date,
        reason=c.reason if include_reason else None,
        status=c.status,
        decided_by=person_ref(session, c.decided_by),
        decided_at=c.decided_at,
        decision_note=c.decision_note,
        created_at=c.created_at,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
        can_approve=can_approve,
        can_cancel=can_cancel,
        requested_at=c.created_at,
        updated_at=latest_activity(c.created_at, c.decided_at, (audit_times or {}).get(c.id)),
        waiting_on=resolve_waiting_on(session, soldier_id=c.soldier_id, status=c.status),
        commander_approved_by=person_ref(session, c.commander_approved_by),
        crossed_holidays=crossed_holidays,
    )


def _can_approve_constraint(
    session: Session,
    user: Soldier,
    target_soldier_id: uuid.UUID,
    target_node: HierarchyNode | None,
    constraint_status: str,
) -> bool:
    """Mirror the authorization in approve()/reject(): a pending-list row's approve
    button should only be shown when a click would actually succeed. Most notably,
    this excludes the viewer's own pending request — forbid_self_target() always
    denies deciding your own request, even for admins, but scope containment alone
    (a commander/duty-manager's own node is typically inside their own subtree)
    doesn't naturally exclude that case.
    """
    if user.id == target_soldier_id:
        return False
    if user.role == "admin":
        return True
    if constraint_status == "pending_duty_manager" and user.role not in ("duty_manager", "admin"):
        return False
    if constraint_status in ("pending", "pending_commander"):
        from app.services.authority import senior_commander_approval_authorized
        if senior_commander_approval_authorized(session, user=user, target_node=target_node):
            return True
        if not is_duty_manager(session, user.id):
            return False
    roots = scope_root_ids(session, user)
    return can(
        user,
        Action.CONSTRAINT_APPROVE,
        target_node=target_node,
        roots=roots,
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
    )


def _nearest_approvers(
    session: Session, soldier_id: uuid.UUID
) -> tuple[NearestApproverOut | None, NearestApproverOut | None]:
    from app.services.approval_scope import (
        nearest_commander_for_soldier,
        nearest_duty_manager_for_soldier,
    )

    cmd_id = nearest_commander_for_soldier(session, soldier_id)
    dm_id = nearest_duty_manager_for_soldier(session, soldier_id)
    cmd = session.get(Soldier, cmd_id) if cmd_id else None
    dm = session.get(Soldier, dm_id) if dm_id else None
    return (
        NearestApproverOut(id=cmd.id, name=cmd.full_name) if cmd else None,
        NearestApproverOut(id=dm.id, name=dm.full_name) if dm else None,
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
    rows = svc.list_constraints(session, soldier_id=user.id)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, user.id)
    audit_times = constraint_audit_latest(session, [c.id for c in rows])
    return [
        _out(
            session,
            c,
            nearest_commander=nearest_commander,
            nearest_duty_manager=nearest_duty_manager,
            audit_times=audit_times,
        )
        for c in rows
    ]


@router.get("/me/constraints/remaining", response_model=RemainingDaysOut)
def my_remaining_constraint_days(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RemainingDaysOut:
    return RemainingDaysOut(**svc.remaining_days(session, soldier_id=user.id))


@router.post("/me/constraints", response_model=ConstraintOut, status_code=status.HTTP_201_CREATED)
def submit(
    body: SubmitRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_enrolled),
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
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, user.id)
    return _out(session, c, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


@router.delete(
    "/me/constraints/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
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


@router.post("/constraints/{constraint_id}/cancel", response_model=ConstraintOut | None)
def privileged_cancel(
    constraint_id: uuid.UUID,
    body: CancelRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ConstraintOut | None:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    s = _load_soldier(session, c.soldier_id)
    if not request_cancellation_authorized(session, user=user, target_node=_node_of(session, s)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    soldier_id = c.soldier_id
    try:
        svc.cancel_constraint(session, constraint_id=constraint_id, actor_id=user.id, reason=body.reason)
    except svc.ConstraintError as exc:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY if str(exc) == "cancellation_reason_required" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    session.commit()
    # A pending-stage cancel deletes the row outright (see cancel_constraint) rather than
    # marking it "cancelled", so there's nothing left to refresh/return in that case.
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        return None
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    return _out(session, c, include_reason=True, nearest_commander=nearest_commander, nearest_duty_manager=nearest_duty_manager)


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
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, soldier_id)
    can_cancel = request_cancellation_authorized(session, user=user, target_node=_node_of(session, s))
    return [
        _out(
            session,
            c,
            include_reason=include_reason,
            nearest_commander=nearest_commander,
            nearest_duty_manager=nearest_duty_manager,
            can_cancel=can_cancel,
        )
        for c in svc.list_constraints(session, soldier_id=soldier_id)
    ]


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
            for n in session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(node_ids)))
            .scalars()
            .all()
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
        nearest_commander, nearest_duty_manager = _nearest_approvers(session, c.soldier_id)
        target_node = nodes_by_id.get(s.hierarchy_node_id) if s and s.hierarchy_node_id else None
        can_approve = _can_approve_constraint(session, user, c.soldier_id, target_node, c.status)
        can_cancel = request_cancellation_authorized(session, user=user, target_node=target_node)
        result.append(
            _out(
                session,
                c,
                soldier_name=soldier_name,
                node_name=node_name,
                include_reason=include_reason,
                nearest_commander=nearest_commander,
                nearest_duty_manager=nearest_duty_manager,
                can_approve=can_approve,
                can_cancel=can_cancel,
            )
        )
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
                .where(PersonalConstraint.status.in_(("pending_commander", "pending_duty_manager")))
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
                    select(PersonalConstraint).where(
                        PersonalConstraint.status.in_(("pending_commander", "pending_duty_manager"))
                    )
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
    forbid_self_target(user, s.id)
    target_node = _node_of(session, s)
    if c.status in ("pending", "pending_commander"):
        if not senior_commander_approval_authorized(session, user=user, target_node=target_node):
            if not (is_duty_manager(session, user.id) and can(user, Action.CONSTRAINT_APPROVE, target_node=target_node, roots=scope_root_ids(session, user), is_commander=is_commander(session, user.id), is_duty_manager=True)):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    else:
        authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    try:
        c = svc.approve_constraint(
            session,
            constraint_id=constraint_id,
            actor_id=user.id,
            decision_note=body.decision_note,
            actor_role=user.role,
        )
    except svc.ConstraintError as exc:
        code = status.HTTP_403_FORBIDDEN if str(exc) == "not_duty_manager" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    session.commit()
    session.refresh(c)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, c.soldier_id)
    return _out(
        session,
        c,
        include_reason=True,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
    )


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
    forbid_self_target(user, s.id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=_node_of(session, s))
    try:
        c = svc.reject_constraint(
            session, constraint_id=constraint_id, actor_id=user.id, decision_note=body.decision_note
        )
    except svc.ConstraintError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(c)
    nearest_commander, nearest_duty_manager = _nearest_approvers(session, c.soldier_id)
    return _out(
        session,
        c,
        include_reason=True,
        nearest_commander=nearest_commander,
        nearest_duty_manager=nearest_duty_manager,
    )
