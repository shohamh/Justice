from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment, HierarchyNode, NotificationType, Soldier, SwapManagerApproval, SwapRequest,
)
from app.services import assignments as assignments_svc
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting
from app.services.reserves import check_reserve_cap
from app.services.eligibility import check_soldier_for_assignment


class SwapError(Exception):
    """Raised on an invalid swap operation."""


def create_request(
    session: Session,
    *,
    requesting_soldier_id: uuid.UUID,
    duty_assignment_id: uuid.UUID,
    target_soldier_id: uuid.UUID | None,
    reason: str | None,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    if assignment.soldier_id != requesting_soldier_id:
        raise SwapError("not_your_duty")
    if assignment.status != "published":
        raise SwapError("not_published")
    if target_soldier_id is not None and target_soldier_id == requesting_soldier_id:
        raise SwapError("cannot_target_self")
    if target_soldier_id is not None:
        eligible, reason = check_soldier_for_assignment(
            session, target_soldier_id, duty_assignment_id
        )
        if not eligible:
            raise SwapError(f"cover_not_eligible:{reason}")
    existing = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == duty_assignment_id,
            SwapRequest.status.in_(["open", "pending_approval"]),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise SwapError("already_pending")
    req = SwapRequest(
        duty_assignment_id=duty_assignment_id,
        duty_date=assignment.start_date,
        requesting_soldier_id=requesting_soldier_id,
        target_soldier_id=target_soldier_id,
        reason=reason,
        status="open",
    )
    session.add(req)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="swap.create",
        entity_type="swap_request",
        entity_id=req.id,
        after={
            "duty_assignment_id": str(duty_assignment_id),
            "duty_date": req.duty_date.isoformat(),
            "target_soldier_id": str(target_soldier_id) if target_soldier_id else None,
            "status": "open",
        },
    )
    if target_soldier_id is not None:
        create_notification(
            session,
            soldier_id=target_soldier_id,
            type=NotificationType.swap_offer_incoming,
            title="הגיעה בקשת החלפה עבורך",
            reference_type="swap_request",
            reference_id=req.id,
            actor_id=actor_id,
        )

    return req


def list_open_board(session: Session, *, for_soldier_id: uuid.UUID) -> list[SwapRequest]:
    """Open postings visible to a soldier: open-to-anyone OR directed at this soldier,
    excluding their own requests."""
    return list(
        session.execute(
            select(SwapRequest)
            .where(
                SwapRequest.status == "open",
                SwapRequest.requesting_soldier_id != for_soldier_id,
                or_(
                    SwapRequest.target_soldier_id.is_(None),
                    SwapRequest.target_soldier_id == for_soldier_id,
                ),
            )
            .order_by(SwapRequest.duty_date.asc())
        )
        .scalars()
        .all()
    )


def list_own(session: Session, *, soldier_id: uuid.UUID) -> list[SwapRequest]:
    return list(
        session.execute(
            select(SwapRequest)
            .where(SwapRequest.requesting_soldier_id == soldier_id)
            .order_by(SwapRequest.created_at.desc())
        )
        .scalars()
        .all()
    )


def _require_approval(session: Session) -> bool:
    try:
        return bool(get_setting(session, "swaps.require_manager_approval"))
    except SettingNotFound:
        return True  # safe default: require approval


def commander_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct commander from the soldier's own node up to the root of
    the hierarchy, excluding the soldier themself if they command their own node."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    nodes = session.execute(
        select(HierarchyNode).where(HierarchyNode.id.in_(node.path_ids))
    ).scalars().all()
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for n in nodes:
        if n.commander_id and n.commander_id != soldier_id and n.commander_id not in seen:
            seen.add(n.commander_id)
            chain.append(n.commander_id)
    return chain


def _create_manager_approval_rows(session: Session, *, req: SwapRequest) -> None:
    """Populate swap_manager_approvals for both sides. Called once, when a swap
    enters pending_approval with a known covering soldier."""
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            continue
        for commander_id in commander_chain_for_soldier(session, soldier_id):
            session.add(SwapManagerApproval(swap_request_id=req.id, side=side, commander_id=commander_id))
    session.flush()


def _all_approved(session: Session, req: SwapRequest) -> bool:
    if not (req.requester_side_approved and req.covering_side_approved):
        return False
    pending = session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == req.id,
            SwapManagerApproval.approved == False,  # noqa: E712
        ).limit(1)
    ).first()
    return pending is None


def _try_finalize(session: Session, req: SwapRequest, actor_id: uuid.UUID | None) -> None:
    if not _all_approved(session, req):
        return
    _apply_cover(session, req=req, actor_id=actor_id)
    create_notification(session, soldier_id=req.requesting_soldier_id,
                        type=NotificationType.swap_accepted,
                        title="בקשת ההחלפה אושרה",
                        reference_type="swap_request", reference_id=req.id,
                        actor_id=actor_id)
    if req.covering_soldier_id:
        create_notification(session, soldier_id=req.covering_soldier_id,
                            type=NotificationType.swap_accepted,
                            title="בקשת ההחלפה אושרה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="swap.apply", entity_type="swap_request",
        entity_id=req.id, after={"status": "applied"},
    )


def approve_soldier_side(
    session: Session, *, request_id: uuid.UUID, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    if soldier_id == req.requesting_soldier_id:
        req.requester_side_approved = True
    elif soldier_id == req.covering_soldier_id:
        req.covering_side_approved = True
    else:
        raise SwapError("not_a_party")
    write_audit(
        session, actor_id=actor_id or soldier_id, action="swap.soldier_approve",
        entity_type="swap_request", entity_id=req.id, after={"soldier_id": str(soldier_id)},
    )
    session.flush()
    _try_finalize(session, req, actor_id or soldier_id)
    session.flush()
    return req


def has_required_manager_row(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID
) -> bool:
    return session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == commander_id,
            SwapManagerApproval.approved == False,  # noqa: E712
        )
    ).first() is not None


def approve_manager_row(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID, actor_id: uuid.UUID
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    row = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == commander_id,
            SwapManagerApproval.approved == False,  # noqa: E712
        )
    ).scalar_one_or_none()
    if row is None:
        raise SwapError("not_required_approver")
    row.approved = True
    row.approved_by = actor_id
    row.approved_at = datetime.utcnow()
    write_audit(
        session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
        entity_id=req.id, after={"side": side, "commander_id": str(commander_id)},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def approve_manager_side_override(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID
) -> SwapRequest:
    """Used when the acting user is authorized (admin / duty-manager / broader
    commander scope) but isn't literally one of the required chain commanders —
    clears every outstanding row for that side at once."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    rows = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.approved == False,  # noqa: E712
        )
    ).scalars().all()
    now = datetime.utcnow()
    for row in rows:
        row.approved = True
        row.approved_by = actor_id
        row.approved_at = now
    write_audit(
        session, actor_id=actor_id, action="swap.manager_approve_override", entity_type="swap_request",
        entity_id=req.id, after={"side": side, "rows_cleared": len(rows)},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def _apply_cover(
    session: Session, *, req: SwapRequest, actor_id: uuid.UUID | None
) -> None:
    """Translate an agreed swap into duty_day_overrides for every day of the assignment."""
    assignment = session.get(DutyAssignment, req.duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    first_ov = None
    current = assignment.start_date
    while current < assignment.end_date:  # end_date is exclusive
        try:
            ov = assignments_svc.set_day_override(
                session,
                assignment=assignment,
                date=current,
                effective_soldier_id=req.covering_soldier_id,
                reason="replacement",
                actor_id=actor_id,
            )
        except assignments_svc.AssignmentError as exc:
            raise SwapError(f"cover_blocked:{exc}") from exc
        if first_ov is None:
            first_ov = ov
        current += timedelta(days=1)
    req.resulting_override_id = first_ov.id if first_ov else None
    req.status = "applied"


def claim_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    covering_soldier_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_open")
    if covering_soldier_id == req.requesting_soldier_id:
        raise SwapError("cannot_cover_own")
    if req.target_soldier_id is not None and req.target_soldier_id != covering_soldier_id:
        raise SwapError("not_targeted_at_you")
    if session.get(Soldier, covering_soldier_id) is None:
        raise SwapError("soldier_not_found")
    eligible, reason = check_soldier_for_assignment(
        session, covering_soldier_id, req.duty_assignment_id
    )
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
    req.covering_soldier_id = covering_soldier_id
    before_status = req.status
    if _require_approval(session):
        req.status = "pending_approval"
        req.requester_side_approved = None
        req.covering_side_approved = None
        _create_manager_approval_rows(session, req=req)
        create_notification(session, soldier_id=req.requesting_soldier_id,
                            type=NotificationType.swap_offer,
                            title="הייתה הצעת החלפה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
        write_audit(
            session, actor_id=actor_id, action="swap.claim", entity_type="swap_request",
            entity_id=req.id, before={"status": before_status},
            after={"status": "pending_approval", "covering_soldier_id": str(covering_soldier_id)},
        )
    else:
        _apply_cover(session, req=req, actor_id=actor_id)
        write_audit(
            session, actor_id=actor_id, action="swap.claim", entity_type="swap_request",
            entity_id=req.id, before={"status": before_status},
            after={"status": "applied", "covering_soldier_id": str(covering_soldier_id)},
        )
    session.flush()
    return req


def reject_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    decision_note: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status not in ("open", "pending_approval"):
        raise SwapError("not_rejectable")
    before = {"status": req.status}
    req.status = "rejected"
    req.decision_note = decision_note
    create_notification(session, soldier_id=req.requesting_soldier_id,
                        type=NotificationType.swap_rejected,
                        title="בקשת ההחלפה נדחתה",
                        reference_type="swap_request", reference_id=req.id,
                        actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="swap.reject", entity_type="swap_request",
        entity_id=req.id, before=before, after={"status": "rejected", "decision_note": decision_note},
    )
    session.flush()
    return req


def cancel_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status not in ("open", "pending_approval"):
        raise SwapError("not_cancellable")
    before = {"status": req.status}
    req.status = "cancelled"
    write_audit(
        session, actor_id=actor_id, action="swap.cancel", entity_type="swap_request",
        entity_id=req.id, before=before, after={"status": "cancelled"},
    )
    session.flush()
    return req


def take_free(
    session: Session,
    *,
    assignment_id: uuid.UUID,
    covering_soldier_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> tuple[SwapRequest, list[str]]:
    """Proactively take another soldier's entire shift without requiring a prior swap request."""
    assignment = session.get(DutyAssignment, assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    if assignment.soldier_id == covering_soldier_id:
        raise SwapError("cannot_take_own_duty")
    if assignment.status != "published":
        raise SwapError("not_published")
    existing = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == assignment_id,
            SwapRequest.status.in_(["open", "pending_approval"]),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise SwapError("already_pending")

    warnings: list[str] = []

    if assignment.is_reserve:
        try:
            allow = bool(get_setting(session, "reserves.allow_take_free"))
        except SettingNotFound:
            allow = True
        if not allow:
            raise SwapError("reserve_take_free_disabled")

        try:
            window = int(get_setting(session, "reserves.window_days"))
        except SettingNotFound:
            window = 30

        passes, current, max_days = check_reserve_cap(
            session, covering_soldier_id,
            assignment.start_date, assignment.end_date,
        )
        if not passes:
            raise SwapError(f"reserve_cap_exceeded:{current}/{max_days}/{window}")

        headroom = max_days - current
        if 0 <= headroom <= 3:
            warnings.append(f"reserve_cap_near:{current}/{max_days}/{window}")

    eligible, reason = check_soldier_for_assignment(
        session, covering_soldier_id, assignment_id
    )
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")

    req = SwapRequest(
        duty_assignment_id=assignment_id,
        duty_date=assignment.start_date,
        requesting_soldier_id=assignment.soldier_id,
        covering_soldier_id=covering_soldier_id,
        offered_assignment_ids=[],
        status="open",
    )
    session.add(req)
    session.flush()

    create_notification(
        session,
        soldier_id=assignment.soldier_id,
        type=NotificationType.swap_offer,
        title="חייל אחר לקח את התורנות שלך",
        reference_type="swap_request",
        reference_id=req.id,
        actor_id=actor_id,
    )

    _apply_cover(session, req=req, actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="swap.take_free",
        entity_type="swap_request", entity_id=req.id,
        after={
            "duty_assignment_id": str(assignment_id),
            "duty_date": req.duty_date.isoformat(),
            "covering_soldier_id": str(covering_soldier_id),
            "status": "applied",
        },
    )
    session.flush()
    return req, warnings


def cover_offer(
    session: Session,
    *,
    swap_id: uuid.UUID,
    covering_soldier_id: uuid.UUID,
    offered_assignment_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    """Covering soldier responds to an open swap request (from board or incoming)."""
    req = session.get(SwapRequest, swap_id)
    if req is None:
        raise SwapError("swap_not_found")
    if req.status != "open":
        raise SwapError("swap_not_open")
    if req.requesting_soldier_id == covering_soldier_id:
        raise SwapError("cannot_cover_own_swap")
    eligible, reason = check_soldier_for_assignment(
        session, covering_soldier_id, req.duty_assignment_id
    )
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
    req.covering_soldier_id = covering_soldier_id
    req.offered_assignment_ids = [str(aid) for aid in offered_assignment_ids]

    if _require_approval(session):
        req.status = "pending_approval"
        req.requester_side_approved = None
        req.covering_side_approved = None
        _create_manager_approval_rows(session, req=req)
        create_notification(
            session,
            soldier_id=req.requesting_soldier_id,
            type=NotificationType.swap_offer,
            title="הגיעה הצעה לכיסוי הבקשה שלך",
            reference_type="swap_request",
            reference_id=req.id,
            actor_id=actor_id,
        )
    else:
        _apply_cover(session, req=req, actor_id=actor_id)

    write_audit(
        session,
        actor_id=actor_id,
        action="swap.cover_offer",
        entity_type="swap_request",
        entity_id=req.id,
        after={
            "covering_soldier_id": str(covering_soldier_id),
            "status": req.status,
        },
    )
    session.flush()
    return req


def list_pending_approval(session: Session) -> list[SwapRequest]:
    return list(
        session.execute(
            select(SwapRequest)
            .where(SwapRequest.status == "pending_approval")
            .order_by(SwapRequest.duty_date.asc())
        )
        .scalars()
        .all()
    )
