from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, DutyLocation, DutyType, HierarchyNode, SwapRequest, Soldier
from app.db.session import get_session
from app.services import swaps as svc
from app.services.eligibility import check_soldier_for_assignment

router = APIRouter(tags=["swaps"])


class CoverEligibilityOut(BaseModel):
    eligible: bool
    reason: str | None


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
    offered_assignment_ids: list[str] = []
    created_at: datetime
    duty_type_name: str | None = None
    duty_location_name: str | None = None
    duty_type_id: uuid.UUID | None = None
    duty_location_id: uuid.UUID | None = None
    duty_start_date: date | None = None
    duty_end_date: date | None = None
    warnings: list[str] = []
    requesting_soldier_name: str | None = None
    covering_soldier_name: str | None = None
    requesting_commander_name: str | None = None
    covering_commander_name: str | None = None
    requesting_soldier_node_name: str | None = None


class CreateSwapRequest(BaseModel):
    duty_assignment_id: uuid.UUID
    target_soldier_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ClaimRequest(BaseModel):
    pass


class ApproveSideRequest(BaseModel):
    side: str  # "requester" | "covering"


class RejectRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)


def _soldier_names(
    session: Session, soldier_id: uuid.UUID | None
) -> tuple[str | None, str | None]:
    """Return (soldier_name, commander_name) for a soldier ID."""
    if soldier_id is None or session is None:
        return None, None
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        return None, None
    commander_name: str | None = None
    if soldier.hierarchy_node_id is not None:
        node = session.get(HierarchyNode, soldier.hierarchy_node_id)
        if node is not None and node.commander_id is not None and node.commander_id != soldier_id:
            commander = session.get(Soldier, node.commander_id)
            if commander is not None:
                commander_name = commander.full_name
    return soldier.full_name, commander_name


def _out(r: SwapRequest, session: Session | None = None, warnings: list[str] | None = None) -> SwapOut:
    duty_type_name = None
    duty_location_name = None
    duty_type_id = None
    duty_location_id = None
    duty_start_date = None
    duty_end_date = None
    requesting_soldier_name, requesting_commander_name = _soldier_names(session, r.requesting_soldier_id)  # type: ignore[arg-type]
    covering_soldier_name, covering_commander_name = _soldier_names(session, r.covering_soldier_id)
    requesting_soldier_node_name: str | None = None
    if session is not None and r.requesting_soldier_id is not None:
        req_soldier = session.get(Soldier, r.requesting_soldier_id)
        if req_soldier is not None and req_soldier.hierarchy_node_id is not None:
            node = session.get(HierarchyNode, req_soldier.hierarchy_node_id)
            if node is not None:
                requesting_soldier_node_name = node.name
    if session is not None:
        assignment = session.get(DutyAssignment, r.duty_assignment_id)
        if assignment is not None:
            duty_type_id = assignment.duty_type_id
            duty_location_id = assignment.duty_location_id
            duty_start_date = assignment.start_date
            duty_end_date = assignment.end_date
            dt = session.get(DutyType, assignment.duty_type_id)
            loc = session.get(DutyLocation, assignment.duty_location_id)
            duty_type_name = dt.name if dt else None
            duty_location_name = loc.name if loc else None
    return SwapOut(
        id=r.id, duty_assignment_id=r.duty_assignment_id, duty_date=r.duty_date,
        requesting_soldier_id=r.requesting_soldier_id, target_soldier_id=r.target_soldier_id,
        covering_soldier_id=r.covering_soldier_id, status=r.status, reason=r.reason,
        requester_side_approved=r.requester_side_approved,
        covering_side_approved=r.covering_side_approved,
        decision_note=r.decision_note,
        offered_assignment_ids=[str(x) for x in (r.offered_assignment_ids or [])],
        created_at=r.created_at,
        duty_type_name=duty_type_name,
        duty_location_name=duty_location_name,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        duty_start_date=duty_start_date,
        duty_end_date=duty_end_date,
        warnings=warnings or [],
        requesting_soldier_name=requesting_soldier_name,
        covering_soldier_name=covering_soldier_name,
        requesting_commander_name=requesting_commander_name,
        covering_commander_name=covering_commander_name,
        requesting_soldier_node_name=requesting_soldier_node_name,
    )


def _err(exc: svc.SwapError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/swaps/config")
def swap_config(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    return {"require_manager_approval": svc._require_approval(session)}


@router.get("/swaps/{assignment_id}/cover-eligibility", response_model=CoverEligibilityOut)
def cover_eligibility(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> CoverEligibilityOut:
    assignment = session.get(DutyAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    eligible, reason = check_soldier_for_assignment(session, user.id, assignment_id)
    return CoverEligibilityOut(eligible=eligible, reason=reason)


@router.get("/me/swaps", response_model=list[SwapOut])
def my_swaps(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    return [_out(r, session) for r in svc.list_own(session, soldier_id=user.id)]


@router.get("/swaps/incoming/count")
def get_incoming_swap_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    count = session.execute(
        select(func.count())
        .select_from(SwapRequest)
        .where(
            SwapRequest.target_soldier_id == user.id,
            SwapRequest.status == "open",
        )
    ).scalar_one()
    return {"count": count}


@router.get("/swaps/incoming", response_model=list[SwapOut])
def list_incoming_swaps(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    rows = session.execute(
        select(SwapRequest).where(
            SwapRequest.target_soldier_id == user.id,
            SwapRequest.status == "open",
        ).order_by(SwapRequest.created_at.desc())
    ).scalars().all()
    return [_out(r, session) for r in rows]


@router.get("/swaps/board", response_model=list[SwapOut])
def board(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    duty_type_id: list[uuid.UUID] = Query(default=[]),
    node_id: list[uuid.UUID] = Query(default=[]),
    eligible_only: bool = Query(default=False),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    rows = svc.list_open_board(session, for_soldier_id=user.id)
    if date_from is not None:
        rows = [r for r in rows if r.duty_date >= date_from]
    if date_to is not None:
        rows = [r for r in rows if r.duty_date <= date_to]
    if duty_type_id:
        type_filter = set(duty_type_id)
        assignment_ids = {r.duty_assignment_id for r in rows}
        type_map: dict[uuid.UUID, uuid.UUID | None] = {}
        for aid in assignment_ids:
            a = session.get(DutyAssignment, aid)
            type_map[aid] = a.duty_type_id if a else None
        rows = [r for r in rows if type_map.get(r.duty_assignment_id) in type_filter]
    if node_id:
        node_filter = set(node_id)
        soldier_ids = {r.requesting_soldier_id for r in rows}
        node_map: dict[uuid.UUID, uuid.UUID | None] = {}
        for sid in soldier_ids:
            s = session.get(Soldier, sid)
            node_map[sid] = s.hierarchy_node_id if s else None
        rows = [r for r in rows if node_map.get(r.requesting_soldier_id) in node_filter]
    if eligible_only:
        rows = [r for r in rows if check_soldier_for_assignment(session, user.id, r.duty_assignment_id)[0]]
    return [_out(r, session) for r in rows]


@router.get("/swaps/for-assignment/{assignment_id}", response_model=list[SwapOut])
def list_swaps_for_assignment(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    rows = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == assignment_id,
            SwapRequest.status == "open",
        )
    ).scalars().all()
    return [_out(r, session) for r in rows]


@router.post("/me/swaps", response_model=SwapOut, status_code=status.HTTP_201_CREATED)
def create(
    body: CreateSwapRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        r = svc.create_request(
            session, requesting_soldier_id=user.id, duty_assignment_id=body.duty_assignment_id,
            target_soldier_id=body.target_soldier_id,
            reason=body.reason, actor_id=user.id,
        )
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


class TakeFreeDutyRequest(BaseModel):
    duty_assignment_id: uuid.UUID


@router.post("/swaps/take-free", response_model=SwapOut, status_code=status.HTTP_201_CREATED)
def take_free(
    body: TakeFreeDutyRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        r, warnings = svc.take_free(
            session,
            assignment_id=body.duty_assignment_id,
            covering_soldier_id=user.id,
            actor_id=user.id,
        )
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session, warnings)


class CoverOfferInput(BaseModel):
    offered_assignment_ids: list[uuid.UUID] = []


@router.post("/swaps/{swap_id}/offer", response_model=SwapOut)
def submit_cover_offer(
    swap_id: uuid.UUID,
    body: CoverOfferInput,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        swap = svc.cover_offer(
            session,
            swap_id=swap_id,
            covering_soldier_id=user.id,
            offered_assignment_ids=body.offered_assignment_ids,
            actor_id=user.id,
        )
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(swap)
    return _out(swap, session)


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
    return _out(r, session)


@router.delete("/me/swaps/{request_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
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
    authorize(session, user, Action.SWAP_APPROVE, target_node=None)
    return [_out(r, session) for r in svc.list_pending_approval(session)]


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
    return _out(r, session)


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
    return _out(r, session)
