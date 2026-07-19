from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, can, is_commander, is_duty_manager, scope_root_ids
from app.auth.deps import require_enrolled, require_password_changed
from app.db.models import DutyAssignment, DutyLocation, DutyType, HierarchyNode, SwapManagerApproval, SwapRequest, Soldier
from app.db.session import get_session
from app.services import swaps as svc
from app.services.eligibility import check_soldier_for_assignment

router = APIRouter(tags=["swaps"])


class CoverEligibilityOut(BaseModel):
    eligible: bool
    reason: str | None


class SwapManagerApprovalOut(BaseModel):
    commander_id: uuid.UUID
    commander_name: str | None = None
    approved: bool
    approved_by: uuid.UUID | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None


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
    duty_shift_id: uuid.UUID | None = None
    warnings: list[str] = []
    requesting_soldier_name: str | None = None
    covering_soldier_name: str | None = None
    requesting_commander_name: str | None = None
    covering_commander_name: str | None = None
    requesting_soldier_node_name: str | None = None
    requester_manager_approvals: list[SwapManagerApprovalOut] = []
    covering_manager_approvals: list[SwapManagerApprovalOut] = []


class CreateSwapRequest(BaseModel):
    duty_assignment_id: uuid.UUID
    target_soldier_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ClaimRequest(BaseModel):
    pass


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


def _manager_approvals_out(session: Session, request_id: uuid.UUID, side: str) -> list[SwapManagerApprovalOut]:
    rows = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
        ).order_by(SwapManagerApproval.created_at)
    ).scalars().all()
    out = []
    for row in rows:
        commander = session.get(Soldier, row.commander_id)
        approved_by = session.get(Soldier, row.approved_by) if row.approved_by else None
        out.append(SwapManagerApprovalOut(
            commander_id=row.commander_id,
            commander_name=commander.full_name if commander else None,
            approved=row.approved,
            approved_by=row.approved_by,
            approved_by_name=approved_by.full_name if approved_by else None,
            approved_at=row.approved_at,
        ))
    return out


def _manager_approvals_out_bulk(
    approvals_by_request: dict[tuple[uuid.UUID, str], list[SwapManagerApproval]],
    approval_soldier_names: dict[uuid.UUID, str | None],
    request_id: uuid.UUID,
    side: str,
) -> list[SwapManagerApprovalOut]:
    """Build SwapManagerApprovalOut list purely from pre-loaded dicts — zero session queries."""
    rows = approvals_by_request.get((request_id, side), [])
    out = []
    for row in rows:
        approved_by_name = approval_soldier_names.get(row.approved_by) if row.approved_by else None
        out.append(SwapManagerApprovalOut(
            commander_id=row.commander_id,
            commander_name=approval_soldier_names.get(row.commander_id),
            approved=row.approved,
            approved_by=row.approved_by,
            approved_by_name=approved_by_name,
            approved_at=row.approved_at,
        ))
    return out


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
    duty_shift_id = None
    if session is not None:
        assignment = session.get(DutyAssignment, r.duty_assignment_id)
        if assignment is not None:
            duty_type_id = assignment.duty_type_id
            duty_location_id = assignment.duty_location_id
            duty_start_date = assignment.start_date
            duty_end_date = assignment.end_date
            duty_shift_id = assignment.duty_shift_id
            dt = session.get(DutyType, assignment.duty_type_id)
            loc = session.get(DutyLocation, assignment.duty_location_id)
            duty_type_name = dt.name if dt else None
            duty_location_name = loc.name if loc else None
    requester_manager_approvals = _manager_approvals_out(session, r.id, "requester") if session is not None else []
    covering_manager_approvals = _manager_approvals_out(session, r.id, "covering") if session is not None else []
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
        duty_shift_id=duty_shift_id,
        warnings=warnings or [],
        requesting_soldier_name=requesting_soldier_name,
        covering_soldier_name=covering_soldier_name,
        requesting_commander_name=requesting_commander_name,
        covering_commander_name=covering_commander_name,
        requesting_soldier_node_name=requesting_soldier_node_name,
        requester_manager_approvals=requester_manager_approvals,
        covering_manager_approvals=covering_manager_approvals,
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
        # Expand each selected node to include its entire subtree via path_ids
        expanded: set[uuid.UUID] = set()
        for nid in node_id:
            subtree_ids = session.execute(
                select(HierarchyNode.id).where(
                    HierarchyNode.path_ids.any(nid)  # type: ignore[arg-type]
                )
            ).scalars().all()
            expanded.update(subtree_ids)
        soldier_ids = {r.requesting_soldier_id for r in rows}
        node_map: dict[uuid.UUID, uuid.UUID | None] = {}
        for sid in soldier_ids:
            s = session.get(Soldier, sid)
            node_map[sid] = s.hierarchy_node_id if s else None
        rows = [r for r in rows if node_map.get(r.requesting_soldier_id) in expanded]
    if eligible_only:
        rows = [r for r in rows if check_soldier_for_assignment(session, user.id, r.duty_assignment_id)[0]]
    return [_out(r, session) for r in rows]


@router.get("/swaps/for-assignment/{assignment_id}", response_model=list[SwapOut])
def list_swaps_for_assignment(
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    assignment = session.get(DutyAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    # Allow: the assignment owner, or a user with SWAP_APPROVE in scope
    is_owner = assignment.soldier_id == user.id
    if not is_owner:
        node = None
        soldier_on_assignment = session.get(Soldier, assignment.soldier_id)
        if soldier_on_assignment and soldier_on_assignment.hierarchy_node_id:
            node = session.get(HierarchyNode, soldier_on_assignment.hierarchy_node_id)
        roots = scope_root_ids(session, user)
        if not can(
            user, Action.SWAP_APPROVE, target_node=node, roots=roots,
            is_commander=is_commander(session, user.id), is_duty_manager=is_duty_manager(session, user.id),
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
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
    user: Soldier = Depends(require_enrolled),
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
    user: Soldier = Depends(require_enrolled),
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
    user: Soldier = Depends(require_enrolled),
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
    user: Soldier = Depends(require_enrolled),
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
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if r.requesting_soldier_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
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
    if user.role not in ("admin", "duty_manager", "commander"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    all_pending = svc.list_pending_approval(session)
    if not all_pending:
        return []

    # Batch-load all related data in a few queries instead of N*8 session.get() calls.
    soldier_ids = set()
    assignment_ids = set()
    for r in all_pending:
        soldier_ids.add(r.requesting_soldier_id)
        if r.covering_soldier_id:
            soldier_ids.add(r.covering_soldier_id)
        assignment_ids.add(r.duty_assignment_id)

    soldiers = {s.id: s for s in session.execute(
        select(Soldier).where(Soldier.id.in_(soldier_ids))
    ).scalars().all()}

    node_ids = {s.hierarchy_node_id for s in soldiers.values() if s.hierarchy_node_id}
    nodes = {n.id: n for n in session.execute(
        select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
    ).scalars().all()} if node_ids else {}

    # Also load commanders referenced by nodes.
    commander_ids = {n.commander_id for n in nodes.values() if n.commander_id} - soldier_ids
    if commander_ids:
        commanders = {s.id: s for s in session.execute(
            select(Soldier).where(Soldier.id.in_(commander_ids))
        ).scalars().all()}
        soldiers.update(commanders)

    assignments = {a.id: a for a in session.execute(
        select(DutyAssignment).where(DutyAssignment.id.in_(assignment_ids))
    ).scalars().all()}

    dt_ids = {a.duty_type_id for a in assignments.values()}
    duty_types = {dt.id: dt for dt in session.execute(
        select(DutyType).where(DutyType.id.in_(dt_ids))
    ).scalars().all()} if dt_ids else {}

    loc_ids = {a.duty_location_id for a in assignments.values()}
    duty_locations = {loc.id: loc for loc in session.execute(
        select(DutyLocation).where(DutyLocation.id.in_(loc_ids))
    ).scalars().all()} if loc_ids else {}

    # Batch-load manager approvals for all pending swaps in one query, instead of
    # 2 queries + N session.get() calls per swap.
    request_ids = {r.id for r in all_pending}
    approval_rows = session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id.in_(request_ids))
        .order_by(SwapManagerApproval.created_at)
    ).scalars().all()
    approvals_by_request: dict[tuple[uuid.UUID, str], list[SwapManagerApproval]] = {}
    approval_person_ids: set[uuid.UUID] = set()
    for row in approval_rows:
        approvals_by_request.setdefault((row.swap_request_id, row.side), []).append(row)
        approval_person_ids.add(row.commander_id)
        if row.approved_by:
            approval_person_ids.add(row.approved_by)

    approval_person_ids -= soldiers.keys()
    approval_soldier_names: dict[uuid.UUID, str | None] = {s.id: s.full_name for s in soldiers.values()}
    if approval_person_ids:
        extra_soldiers = session.execute(
            select(Soldier).where(Soldier.id.in_(approval_person_ids))
        ).scalars().all()
        approval_soldier_names.update({s.id: s.full_name for s in extra_soldiers})

    def _side_node_bulk(r: SwapRequest, soldier_id: uuid.UUID | None) -> HierarchyNode | None:
        if soldier_id is None:
            return None
        s = soldiers.get(soldier_id)
        if s is None or s.hierarchy_node_id is None:
            return None
        return nodes.get(s.hierarchy_node_id)

    if user.role == "admin":
        return [
            _out_bulk(
                session, r, soldiers, nodes, assignments, duty_types, duty_locations,
                approvals_by_request, approval_soldier_names,
            )
            for r in all_pending
        ]

    roots = scope_root_ids(session, user)
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)
    return [
        _out_bulk(
            session, r, soldiers, nodes, assignments, duty_types, duty_locations,
            approvals_by_request, approval_soldier_names,
        )
        for r in all_pending
        if can(
            user, Action.SWAP_APPROVE, target_node=_side_node_bulk(r, r.requesting_soldier_id), roots=roots,
            is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
        ) or can(
            user, Action.SWAP_APPROVE, target_node=_side_node_bulk(r, r.covering_soldier_id), roots=roots,
            is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
        )
    ]


def _out_bulk(
    session: Session,
    r: SwapRequest,
    soldiers: dict,
    nodes: dict,
    assignments: dict,
    duty_types: dict,
    duty_locations: dict,
    approvals_by_request: dict[tuple[uuid.UUID, str], list[SwapManagerApproval]],
    approval_soldier_names: dict[uuid.UUID, str | None],
    warnings: list[str] | None = None,
) -> SwapOut:
    """Build SwapOut from pre-loaded dicts — zero session.get() calls."""
    def _soldier_name(sid):
        s = soldiers.get(sid)
        return s.full_name if s else None

    def _commander_name(sid):
        s = soldiers.get(sid)
        if s is None or s.hierarchy_node_id is None:
            return None
        node = nodes.get(s.hierarchy_node_id)
        if node is None or node.commander_id is None or node.commander_id == sid:
            return None
        commander = soldiers.get(node.commander_id)
        return commander.full_name if commander else None

    def _node_name(sid):
        s = soldiers.get(sid)
        if s is None or s.hierarchy_node_id is None:
            return None
        node = nodes.get(s.hierarchy_node_id)
        return node.name if node else None

    assignment = assignments.get(r.duty_assignment_id)
    dt = duty_types.get(assignment.duty_type_id) if assignment else None
    loc = duty_locations.get(assignment.duty_location_id) if assignment else None

    requester_manager_approvals = _manager_approvals_out_bulk(
        approvals_by_request, approval_soldier_names, r.id, "requester"
    )
    covering_manager_approvals = _manager_approvals_out_bulk(
        approvals_by_request, approval_soldier_names, r.id, "covering"
    )

    return SwapOut(
        id=r.id, duty_assignment_id=r.duty_assignment_id, duty_date=r.duty_date,
        requesting_soldier_id=r.requesting_soldier_id,
        target_soldier_id=r.target_soldier_id,
        covering_soldier_id=r.covering_soldier_id,
        status=r.status, reason=r.reason,
        requester_side_approved=r.requester_side_approved,
        covering_side_approved=r.covering_side_approved,
        decision_note=r.decision_note,
        offered_assignment_ids=[str(x) for x in (r.offered_assignment_ids or [])],
        created_at=r.created_at,
        duty_type_name=dt.name if dt else None,
        duty_location_name=loc.name if loc else None,
        duty_type_id=assignment.duty_type_id if assignment else None,
        duty_location_id=assignment.duty_location_id if assignment else None,
        duty_start_date=assignment.start_date if assignment else None,
        duty_end_date=assignment.end_date if assignment else None,
        duty_shift_id=assignment.duty_shift_id if assignment else None,
        warnings=warnings or [],
        requesting_soldier_name=_soldier_name(r.requesting_soldier_id),
        covering_soldier_name=_soldier_name(r.covering_soldier_id),
        requesting_commander_name=_commander_name(r.requesting_soldier_id),
        covering_commander_name=_commander_name(r.covering_soldier_id),
        requesting_soldier_node_name=_node_name(r.requesting_soldier_id),
        requester_manager_approvals=requester_manager_approvals,
        covering_manager_approvals=covering_manager_approvals,
    )


@router.post("/me/swaps/{request_id}/approve", response_model=SwapOut)
def soldier_approve(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        r = svc.approve_soldier_side(session, request_id=request_id, soldier_id=user.id, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


@router.post("/me/swaps/{request_id}/reject", response_model=SwapOut)
def soldier_reject(
    request_id: uuid.UUID,
    body: RejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if user.id not in (req.requesting_soldier_id, req.covering_soldier_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        r = svc.reject_request(session, request_id=request_id, decision_note=body.decision_note, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


class ManagerSideRequest(BaseModel):
    side: str  # "requester" | "covering"


def _side_node(session: Session, req: SwapRequest, side: str) -> HierarchyNode | None:
    soldier_id = req.requesting_soldier_id if side == "requester" else req.covering_soldier_id
    if soldier_id is None:
        return None
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return None
    return session.get(HierarchyNode, soldier.hierarchy_node_id)


@router.post("/swaps/{request_id}/manager-approve", response_model=SwapOut)
def manager_approve(
    request_id: uuid.UUID,
    body: ManagerSideRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="swap_not_found")
    if body.side not in ("requester", "covering"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad_side")
    def _override_authorized() -> bool:
        authorize(session, user, Action.SWAP_APPROVE, target_node=_side_node(session, req, body.side))
        return True

    try:
        r = svc.approve_manager_side(
            session, request_id=request_id, side=body.side, actor_id=user.id,
            is_authorized_override=_override_authorized,
        )
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


@router.post("/swaps/{request_id}/manager-reject", response_model=SwapOut)
def manager_reject(
    request_id: uuid.UUID,
    body: RejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="swap_not_found")
    req_node = _side_node(session, req, "requester")
    cov_node = _side_node(session, req, "covering")
    authorized = False
    for node in (req_node, cov_node):
        try:
            authorize(session, user, Action.SWAP_APPROVE, target_node=node)
            authorized = True
            break
        except HTTPException:
            continue
    if not authorized:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        r = svc.reject_request(session, request_id=request_id, decision_note=body.decision_note, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)
