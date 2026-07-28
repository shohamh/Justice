from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, can, is_commander, is_duty_manager, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, ForcedCallup, HierarchyNode, NotificationType, Soldier
from app.db.session import get_session
from app.services import hakpaza as svc
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting

router = APIRouter(prefix="/hakpaza", tags=["hakpaza"])


def _require_hakpaza_enabled(session: Session) -> None:
    try:
        enabled = get_setting(session, "forced_callup.enabled")
    except SettingNotFound:
        enabled = False  # disabled by default
    if not bool(enabled):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="hakpaza_disabled")


def _require_commander_or_dm(session: Session, actor: Soldier) -> None:
    if (
        actor.role != "admin"
        and not is_commander(session, actor.id)
        and not is_duty_manager(session, actor.id)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def _require_dm(session: Session, actor: Soldier) -> None:
    if actor.role != "admin" and not is_duty_manager(session, actor.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def _authorize_assignment_scope(
    session: Session,
    actor: Soldier,
    assignment_id: uuid.UUID,
) -> DutyAssignment:
    """Load assignment and verify actor has ASSIGNMENT_MANAGE scope over its soldier. Returns assignment."""
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    soldier = session.get(Soldier, a.soldier_id)
    target_node: HierarchyNode | None = None
    if soldier and soldier.hierarchy_node_id:
        target_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    # admin bypasses scope checks; duty_manager uses ASSIGNMENT_MANAGE; commanders
    # use HIERARCHY_READ (scope check) since ASSIGNMENT_MANAGE is DM-only by design.
    if actor.role == "admin":
        return a
    roots = scope_root_ids(session, actor)
    actor_is_duty_manager = is_duty_manager(session, actor.id)
    action = Action.ASSIGNMENT_MANAGE if actor_is_duty_manager else Action.HIERARCHY_READ
    if not can(
        actor, action, target_node=target_node, roots=roots,
        is_commander=is_commander(session, actor.id), is_duty_manager=actor_is_duty_manager,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return a


class CandidateRequest(BaseModel):
    pulled_assignment_id: uuid.UUID
    pull_date: date
    n: int = 8


class CandidateOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    hierarchy_node_name: str
    hierarchy_distance: int
    current_score: float
    score_per_day: float
    days_remaining: int
    recent_forced_callups_decayed: float


class CreateHakpazaRequest(BaseModel):
    pulled_assignment_id: uuid.UUID
    pull_date: date
    replacement_soldier_id: uuid.UUID


class HakpazaOut(BaseModel):
    id: uuid.UUID
    initiator_id: uuid.UUID
    pulled_soldier_id: uuid.UUID
    original_assignment_id: uuid.UUID
    pull_date: date
    replacement_soldier_id: uuid.UUID
    replacement_assignment_id: uuid.UUID | None
    status: str
    approver_id: uuid.UUID | None
    approved_at: datetime | None
    callup_multiplier: Decimal
    created_at: datetime


def _out(h: ForcedCallup) -> HakpazaOut:
    return HakpazaOut(
        id=h.id, initiator_id=h.initiator_id, pulled_soldier_id=h.pulled_soldier_id,
        original_assignment_id=h.original_assignment_id, pull_date=h.pull_date,
        replacement_soldier_id=h.replacement_soldier_id,
        replacement_assignment_id=h.replacement_assignment_id,
        status=h.status, approver_id=h.approver_id, approved_at=h.approved_at,
        callup_multiplier=h.callup_multiplier, created_at=h.created_at,
    )


@router.post("/candidates", response_model=list[CandidateOut])
def find_candidates(
    req: CandidateRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    _require_hakpaza_enabled(session)
    _require_commander_or_dm(session, actor)
    _authorize_assignment_scope(session, actor, req.pulled_assignment_id)
    candidates = svc.find_candidates(
        session,
        original_assignment_id=req.pulled_assignment_id,
        pull_date=req.pull_date,
        n=req.n,
    )
    return [CandidateOut(**c) for c in candidates]


@router.post("", response_model=HakpazaOut, status_code=201)
def create_hakpaza(
    req: CreateHakpazaRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    _require_hakpaza_enabled(session)
    _require_commander_or_dm(session, actor)
    original = _authorize_assignment_scope(session, actor, req.pulled_assignment_id)

    try:
        multiplier = Decimal(str(get_setting(session, "hakpaza.callup_multiplier")))
    except Exception:
        multiplier = Decimal("2.0")

    h = ForcedCallup(
        initiator_id=actor.id,
        pulled_soldier_id=original.soldier_id,
        original_assignment_id=req.pulled_assignment_id,
        pull_date=req.pull_date,
        replacement_soldier_id=req.replacement_soldier_id,
        callup_multiplier=multiplier,
    )
    session.add(h)
    session.commit()
    session.refresh(h)
    return _out(h)


@router.get("", response_model=list[HakpazaOut])
def list_hakpazot(
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    _require_hakpaza_enabled(session)
    _require_commander_or_dm(session, actor)
    all_items = session.execute(
        select(ForcedCallup).order_by(ForcedCallup.created_at.desc())
    ).scalars().all()
    if actor.role == "admin":
        return [_out(h) for h in all_items]
    roots = scope_root_ids(session, actor)
    result = []
    for h in all_items:
        pulled = session.get(Soldier, h.pulled_soldier_id)
        if pulled and pulled.hierarchy_node_id:
            node = session.get(HierarchyNode, pulled.hierarchy_node_id)
            if node and any(r in node.path_ids for r in roots):
                result.append(_out(h))
    return result


@router.get("/pending-count")
def pending_count(
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
) -> dict:
    _require_hakpaza_enabled(session)
    if actor.role != "admin" and not is_duty_manager(session, actor.id):
        return {"count": 0}
    count = len(session.execute(
        select(ForcedCallup).where(ForcedCallup.status == "pending")
    ).scalars().all())
    return {"count": count}


@router.post("/{hakpaza_id}/approve", response_model=HakpazaOut)
def approve(
    hakpaza_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    _require_hakpaza_enabled(session)
    _require_dm(session, actor)
    h = session.get(ForcedCallup, hakpaza_id)
    if not h or h.status != "pending":
        raise HTTPException(status_code=404, detail="not_found_or_not_pending")
    pulled = session.get(Soldier, h.pulled_soldier_id)
    if pulled and pulled.hierarchy_node_id:
        node = session.get(HierarchyNode, pulled.hierarchy_node_id)
        authorize(session, actor, Action.ASSIGNMENT_MANAGE, target_node=node)

    original = session.get(DutyAssignment, h.original_assignment_id)
    if not original:
        raise HTTPException(status_code=404, detail="original_assignment_not_found")

    original_end_date = original.end_date
    original.end_date = h.pull_date - timedelta(days=1)

    new_assignment = DutyAssignment(
        soldier_id=h.replacement_soldier_id,
        duty_type_id=original.duty_type_id,
        duty_location_id=original.duty_location_id,
        start_date=h.pull_date,
        end_date=original_end_date,
        status="published",
        is_reserve=False,
        forced_call_up_multiplier=h.callup_multiplier,
        notes=f"הקפצה פיקודית — מחליף {session.get(Soldier, h.pulled_soldier_id).full_name if session.get(Soldier, h.pulled_soldier_id) else ''}",
    )
    session.add(new_assignment)
    session.flush()

    h.status = "approved"
    h.approver_id = actor.id
    h.approved_at = datetime.now(timezone.utc)
    h.replacement_assignment_id = new_assignment.id

    create_notification(
        session, soldier_id=h.pulled_soldier_id,
        type=NotificationType.assignment_removed,
        title="שוחררת מתורנות עקב הקפצה פיקודית",
        reference_type="duty_assignment", reference_id=original.id,
        actor_id=actor.id,
    )
    create_notification(
        session, soldier_id=h.replacement_soldier_id,
        type=NotificationType.assignment_created,
        title="שובצת לתורנות עקב הקפצה פיקודית",
        reference_type="duty_assignment", reference_id=new_assignment.id,
        actor_id=actor.id,
    )

    session.commit()
    session.refresh(h)
    return _out(h)


@router.post("/{hakpaza_id}/reject", response_model=HakpazaOut)
def reject(
    hakpaza_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    _require_hakpaza_enabled(session)
    _require_dm(session, actor)
    h = session.get(ForcedCallup, hakpaza_id)
    if not h or h.status != "pending":
        raise HTTPException(status_code=404, detail="not_found_or_not_pending")
    pulled = session.get(Soldier, h.pulled_soldier_id)
    if pulled and pulled.hierarchy_node_id:
        node = session.get(HierarchyNode, pulled.hierarchy_node_id)
        authorize(session, actor, Action.ASSIGNMENT_MANAGE, target_node=node)
    h.status = "rejected"
    h.approver_id = actor.id
    h.approved_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(h)
    return _out(h)
