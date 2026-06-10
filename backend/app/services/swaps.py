from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyAssignment, NotificationType, Soldier, SwapRequest
from app.services import assignments as assignments_svc
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting
from app.services.reserves import check_reserve_cap


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


def _apply_cover(
    session: Session, *, req: SwapRequest, actor_id: uuid.UUID | None
) -> None:
    """Translate an agreed swap into duty_day_overrides for every day of the assignment."""
    assignment = session.get(DutyAssignment, req.duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    first_ov = None
    current = assignment.start_date
    while current <= assignment.end_date:
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
    req.covering_soldier_id = covering_soldier_id
    before_status = req.status
    if _require_approval(session):
        req.status = "pending_approval"
        req.requester_side_approved = None
        req.covering_side_approved = None
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


def approve_side(
    session: Session,
    *,
    request_id: uuid.UUID,
    side: str,  # "requester" | "covering"
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    if side == "requester":
        req.requester_side_approved = True
    elif side == "covering":
        req.covering_side_approved = True
    else:
        raise SwapError("bad_side")
    write_audit(
        session, actor_id=actor_id, action="swap.approve_side", entity_type="swap_request",
        entity_id=req.id, after={"side": side},
    )
    if req.requester_side_approved and req.covering_side_approved:
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
) -> SwapRequest:
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

    if assignment.is_reserve:
        try:
            allow = bool(get_setting(session, "reserves.allow_take_free"))
        except SettingNotFound:
            allow = True
        if not allow:
            raise SwapError("reserve_take_free_disabled")

        passes, current, max_days = check_reserve_cap(
            session, covering_soldier_id,
            assignment.start_date, assignment.end_date,
        )
        if not passes:
            raise SwapError(f"reserve_cap_exceeded:{current}/{max_days}")

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
    return req


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

    req.covering_soldier_id = covering_soldier_id
    req.offered_assignment_ids = [str(aid) for aid in offered_assignment_ids]

    if _require_approval(session):
        req.status = "pending_approval"
        req.requester_side_approved = None
        req.covering_side_approved = None
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
