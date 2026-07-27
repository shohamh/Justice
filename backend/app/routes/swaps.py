from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, can, is_commander, is_duty_manager, scope_root_ids
from app.auth.deps import require_enrolled, require_password_changed
from app.db.models import (
    DutyAssignment, DutyLocation, DutyType, HierarchyNode, SwapCandidate, SwapManagerApproval, SwapRequest, Soldier,
)
from app.db.session import get_session
from app.services import swaps as svc
from app.services.eligibility import check_soldier_for_assignment

router = APIRouter(tags=["swaps"])


class CoverEligibilityOut(BaseModel):
    eligible: bool
    reason: str | None


class EligibleTargetOut(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    node_name: str | None
    hierarchy_distance: int


class SwapManagerApprovalOut(BaseModel):
    commander_id: uuid.UUID
    commander_name: str | None = None
    approved: bool
    approved_by: uuid.UUID | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    rejected: bool = False
    rejected_by: uuid.UUID | None = None
    rejected_by_name: str | None = None
    rejected_at: datetime | None = None
    approver_kind: str


class SwapCandidateOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str | None = None
    source: str
    status: str
    soldier_side_approved: bool | None = None
    offered_assignment_ids: list[str] = []
    manager_approvals: list[SwapManagerApprovalOut] = []


class SwapOut(BaseModel):
    id: uuid.UUID
    duty_assignment_id: uuid.UUID
    duty_date: date
    requesting_soldier_id: uuid.UUID
    open_to_marketplace: bool
    status: str
    reason: str | None
    requester_side_approved: bool | None
    decision_note: str | None
    rejected_by_name: str | None = None
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
    requesting_commander_name: str | None = None
    requesting_soldier_node_name: str | None = None
    requester_manager_approvals: list[SwapManagerApprovalOut] = []
    candidates: list[SwapCandidateOut] = []


class CreateSwapRequest(BaseModel):
    duty_assignment_id: uuid.UUID
    target_soldier_id: uuid.UUID | None = None
    target_soldier_ids: list[uuid.UUID] | None = None
    open_to_marketplace: bool = False
    reason: str | None = Field(default=None, max_length=1000)


class ClaimRequest(BaseModel):
    pass


class RejectRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)


class ManagerRejectRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)
    candidate_id: uuid.UUID | None = None


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


def _manager_approvals_out(
    session: Session, request_id: uuid.UUID, soldier_id: uuid.UUID, side: str, *, candidate_id: uuid.UUID | None,
) -> list[SwapManagerApprovalOut]:
    """Live-compute the full approval roster for one side of a swap: every
    commander/duty-manager currently in scope for `soldier_id`, cross-referenced
    against whatever SwapManagerApproval decision rows already exist (rows are
    now created lazily, only once someone actually approves/rejects — see
    app.services.swaps — so a chain member with no row yet still shows up here
    with approved=False/rejected=False)."""
    from app.services.approval_scope import commander_chain_for_soldier, duty_manager_chain_for_soldier
    from app.services.swaps import _require_duty_manager_approval

    decisions_by_person_kind = {
        (row.commander_id, row.approver_kind): row
        for row in session.execute(
            select(SwapManagerApproval).where(
                SwapManagerApproval.swap_request_id == request_id,
                SwapManagerApproval.swap_candidate_id == candidate_id,
                SwapManagerApproval.side == side,
            )
        ).scalars().all()
    }

    chains: list[tuple[str, uuid.UUID]] = [("commander", cid) for cid in commander_chain_for_soldier(session, soldier_id)]
    if _require_duty_manager_approval(session):
        chains += [("duty_manager", did) for did in duty_manager_chain_for_soldier(session, soldier_id)]

    out = []
    consumed_keys: set[tuple[uuid.UUID, str]] = set()
    for kind, person_id in chains:
        key = (person_id, kind)
        consumed_keys.add(key)
        row = decisions_by_person_kind.get(key)
        person = session.get(Soldier, person_id)
        approved_by = session.get(Soldier, row.approved_by) if row and row.approved_by else None
        rejected_by = session.get(Soldier, row.rejected_by) if row and row.rejected_by else None
        out.append(SwapManagerApprovalOut(
            commander_id=person_id,
            commander_name=person.full_name if person else None,
            approved=bool(row.approved) if row else False,
            approved_by=row.approved_by if row else None,
            approved_by_name=approved_by.full_name if approved_by else None,
            approved_at=row.approved_at if row else None,
            rejected=bool(row.rejected) if row else False,
            rejected_by=row.rejected_by if row else None,
            rejected_by_name=rejected_by.full_name if rejected_by else None,
            rejected_at=row.rejected_at if row else None,
            approver_kind=kind,
        ))

    # Surface decision rows that don't belong to any live chain member — these are
    # "override" decisions (see app.services.swaps.approve_manager_side_override),
    # where an authorized-but-not-chain-member actor (admin/duty-manager/broader
    # commander) cleared the whole side on the chain's behalf. The row's
    # commander_id is the override actor's own id, so it never matches a chain
    # entry above and would otherwise vanish from the displayed roster even
    # though it fully satisfies (and may have finalized) this side. Appended
    # after the live chain rows so `approvals[0]` (the "direct" commander/duty
    # manager) still comes from the chain; existing frontend logic
    # (isSideSatisfied / DirectCommanderApproval's "approved by other") already
    # picks these up correctly since it just scans the full list for an
    # approved=True row.
    for key, row in decisions_by_person_kind.items():
        if key in consumed_keys:
            continue
        if not (row.approved or row.rejected):
            continue
        person = session.get(Soldier, row.commander_id)
        approved_by = session.get(Soldier, row.approved_by) if row.approved_by else None
        rejected_by = session.get(Soldier, row.rejected_by) if row.rejected_by else None
        out.append(SwapManagerApprovalOut(
            commander_id=row.commander_id,
            commander_name=person.full_name if person else None,
            approved=bool(row.approved),
            approved_by=row.approved_by,
            approved_by_name=approved_by.full_name if approved_by else None,
            approved_at=row.approved_at,
            rejected=bool(row.rejected),
            rejected_by=row.rejected_by,
            rejected_by_name=rejected_by.full_name if rejected_by else None,
            rejected_at=row.rejected_at,
            approver_kind=row.approver_kind,
        ))
    return out


def _candidate_out(session: Session, candidate: SwapCandidate) -> SwapCandidateOut:
    soldier = session.get(Soldier, candidate.soldier_id)
    manager_approvals = _manager_approvals_out(session, candidate.swap_request_id, candidate.soldier_id, "covering", candidate_id=candidate.id)
    return SwapCandidateOut(
        id=candidate.id, soldier_id=candidate.soldier_id,
        soldier_name=soldier.full_name if soldier else None,
        source=candidate.source, status=candidate.status,
        soldier_side_approved=candidate.soldier_side_approved,
        offered_assignment_ids=[str(x) for x in (candidate.offered_assignment_ids or [])],
        manager_approvals=manager_approvals,
    )


def _out(r: SwapRequest, session: Session | None = None, warnings: list[str] | None = None) -> SwapOut:
    duty_type_name = None
    duty_location_name = None
    duty_type_id = None
    duty_location_id = None
    duty_start_date = None
    duty_end_date = None
    requesting_soldier_name, requesting_commander_name = _soldier_names(session, r.requesting_soldier_id)  # type: ignore[arg-type]
    requesting_soldier_node_name: str | None = None
    if session is not None:
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
    requester_manager_approvals = _manager_approvals_out(session, r.id, r.requesting_soldier_id, "requester", candidate_id=None) if session is not None else []
    rejected_by_name = None
    if session is not None and r.rejected_by:
        rejected_by_soldier = session.get(Soldier, r.rejected_by)
        rejected_by_name = rejected_by_soldier.full_name if rejected_by_soldier else None
    candidates_out: list[SwapCandidateOut] = []
    if session is not None:
        candidate_rows = session.execute(
            select(SwapCandidate).where(SwapCandidate.swap_request_id == r.id).order_by(SwapCandidate.created_at.asc())
        ).scalars().all()
        candidates_out = [_candidate_out(session, c) for c in candidate_rows]
    return SwapOut(
        id=r.id, duty_assignment_id=r.duty_assignment_id, duty_date=r.duty_date,
        requesting_soldier_id=r.requesting_soldier_id, open_to_marketplace=r.open_to_marketplace,
        status=r.status, reason=r.reason,
        requester_side_approved=r.requester_side_approved,
        decision_note=r.decision_note,
        rejected_by_name=rejected_by_name,
        created_at=r.created_at,
        duty_type_name=duty_type_name, duty_location_name=duty_location_name,
        duty_type_id=duty_type_id, duty_location_id=duty_location_id,
        duty_start_date=duty_start_date, duty_end_date=duty_end_date, duty_shift_id=duty_shift_id,
        warnings=warnings or [],
        requesting_soldier_name=requesting_soldier_name,
        requesting_commander_name=requesting_commander_name,
        requesting_soldier_node_name=requesting_soldier_node_name,
        requester_manager_approvals=requester_manager_approvals,
        candidates=candidates_out,
    )


def _err(exc: svc.SwapError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/swaps/config")
def swap_config(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    return {
        "require_manager_approval": svc._require_approval(session),
        "require_duty_manager_approval": svc._require_duty_manager_approval(session),
        "max_specific_targets": svc._max_specific_targets(session),
    }


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


@router.get("/swaps/eligible-targets", response_model=list[EligibleTargetOut])
def eligible_targets(
    duty_assignment_id: uuid.UUID = Query(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[EligibleTargetOut]:
    from app.services import swap_targets

    return [
        EligibleTargetOut(**r)
        for r in swap_targets.list_eligible_targets(
            session, requesting_soldier_id=user.id, duty_assignment_id=duty_assignment_id
        )
    ]


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
    request_ids = session.execute(
        select(SwapCandidate.swap_request_id).where(
            SwapCandidate.soldier_id == user.id,
            SwapCandidate.source == "invited",
            SwapCandidate.status == "pending",
        )
    ).scalars().all()
    if not request_ids:
        return {"count": 0}
    count = session.execute(
        select(func.count())
        .select_from(SwapRequest)
        .where(
            SwapRequest.id.in_(request_ids),
            SwapRequest.status == "open",
        )
    ).scalar_one()
    return {"count": count}


@router.get("/swaps/incoming", response_model=list[SwapOut])
def list_incoming_swaps(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    request_ids = session.execute(
        select(SwapCandidate.swap_request_id).where(
            SwapCandidate.soldier_id == user.id,
            SwapCandidate.source == "invited",
            SwapCandidate.status == "pending",
        )
    ).scalars().all()
    if not request_ids:
        return []
    rows = session.execute(
        select(SwapRequest).where(
            SwapRequest.id.in_(request_ids), SwapRequest.status == "open",
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
            target_soldier_id=body.target_soldier_id, target_soldier_ids=body.target_soldier_ids,
            open_to_marketplace=body.open_to_marketplace,
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


def _soldier_node(session: Session, soldier_id: uuid.UUID | None) -> HierarchyNode | None:
    if soldier_id is None:
        return None
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return None
    return session.get(HierarchyNode, soldier.hierarchy_node_id)


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

    if user.role == "admin":
        return [_out(r, session) for r in all_pending]

    roots = scope_root_ids(session, user)
    user_is_commander = is_commander(session, user.id)
    user_is_duty_manager = is_duty_manager(session, user.id)

    def _visible(r: SwapRequest) -> bool:
        if can(
            user, Action.SWAP_APPROVE, target_node=_soldier_node(session, r.requesting_soldier_id), roots=roots,
            is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
        ):
            return True
        candidates = session.execute(
            select(SwapCandidate).where(SwapCandidate.swap_request_id == r.id)
        ).scalars().all()
        for candidate in candidates:
            if can(
                user, Action.SWAP_APPROVE, target_node=_soldier_node(session, candidate.soldier_id), roots=roots,
                is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
            ):
                return True
        return False

    return [_out(r, session) for r in all_pending if _visible(r)]


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
    try:
        if user.id == req.requesting_soldier_id:
            r = svc.reject_request(session, request_id=request_id, decision_note=body.decision_note, actor_id=user.id)
        else:
            svc.decline_candidate(session, request_id=request_id, soldier_id=user.id, actor_id=user.id)
            r = session.get(SwapRequest, request_id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


class ManagerSideRequest(BaseModel):
    side: str  # "requester" | "covering"
    candidate_id: uuid.UUID | None = None


def _side_node(session: Session, req: SwapRequest, side: str, candidate_id: uuid.UUID | None) -> HierarchyNode | None:
    if side == "requester":
        soldier_id = req.requesting_soldier_id
    else:
        if candidate_id is None:
            return None
        candidate = session.get(SwapCandidate, candidate_id)
        if candidate is not None and candidate.swap_request_id != req.id:
            raise svc.SwapError("candidate_mismatch")
        soldier_id = candidate.soldier_id if candidate else None
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
    if body.side == "covering" and body.candidate_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="candidate_id_required")

    def _override_authorized() -> bool:
        authorize(session, user, Action.SWAP_APPROVE, target_node=_side_node(session, req, body.side, body.candidate_id))
        return True

    try:
        r = svc.approve_manager_side(
            session, request_id=request_id, side=body.side, actor_id=user.id,
            is_authorized_override=_override_authorized,
            candidate_id=body.candidate_id,
        )
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)


@router.post("/swaps/{request_id}/manager-reject", response_model=SwapOut)
def manager_reject(
    request_id: uuid.UUID,
    body: ManagerRejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="swap_not_found")
    req_node = _side_node(session, req, "requester", None)

    def _authorized_via_requester() -> bool:
        if req_node is None:
            return False
        try:
            authorize(session, user, Action.SWAP_APPROVE, target_node=req_node)
            return True
        except HTTPException:
            return False

    if not _authorized_via_requester() and body.candidate_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="candidate_id_required")

    # _side_node can raise SwapError("candidate_mismatch") when candidate_id
    # belongs to a different swap request. Keep it inside a try so that
    # surfaces as a 400 (same as manager_approve does) rather than an
    # uncaught 500.
    try:
        cov_node = _side_node(session, req, "covering", body.candidate_id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    authorized = False
    for node in (req_node, cov_node):
        if node is None:
            continue
        try:
            authorize(session, user, Action.SWAP_APPROVE, target_node=node)
            authorized = True
            break
        except HTTPException:
            continue
    if not authorized:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        r = svc.reject_manager_row(
            session, request_id=request_id, actor_id=user.id, decision_note=body.decision_note,
            candidate_id=body.candidate_id,
            # The authorize() sweep above already cleared this actor against
            # the requester's and/or the candidate's node (admins, broader-
            # scope commanders included). Tell the service so it doesn't
            # refuse an actor who holds no literal chain row of their own —
            # same override mechanism manager_approve hands to
            # approve_manager_side.
            is_authorized_override=True,
        )
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r, session)
