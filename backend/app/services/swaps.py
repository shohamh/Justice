from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment, NotificationType, Soldier, SwapManagerApproval, SwapRequest,
)
from app.services import assignments as assignments_svc
from app.services.approval_scope import commander_chain_for_soldier, duty_manager_chain_for_soldier
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting, get_setting_int
from app.services.reserves import check_reserve_cap
from app.services.eligibility import check_soldier_for_assignment


class SwapError(Exception):
    """Raised on an invalid swap operation."""


def _enforce_hierarchy_level_restriction(
    session: Session, *, requesting_soldier_id: uuid.UUID, other_soldier_id: uuid.UUID
) -> None:
    """If swaps.restrict_to_hierarchy_level is set, ensure both soldiers share a common
    ancestor at that level. Raises SwapError("hierarchy_level_mismatch") otherwise."""
    try:
        level = get_setting(session, "swaps.restrict_to_hierarchy_level")
    except SettingNotFound:
        level = None
    if not level:
        return

    from app.services.hierarchy import ancestor_id_at_level

    requester = session.get(Soldier, requesting_soldier_id)
    other = session.get(Soldier, other_soldier_id)
    req_ancestor = (
        ancestor_id_at_level(session, requester.hierarchy_node_id, level)
        if requester.hierarchy_node_id
        else None
    )
    other_ancestor = (
        ancestor_id_at_level(session, other.hierarchy_node_id, level)
        if other.hierarchy_node_id
        else None
    )
    if req_ancestor is None or req_ancestor != other_ancestor:
        raise SwapError("hierarchy_level_mismatch")


def _max_specific_targets(session: Session) -> int:
    return get_setting_int(session, "swaps.max_specific_targets", 5)


def create_request(
    session: Session,
    *,
    requesting_soldier_id: uuid.UUID,
    duty_assignment_id: uuid.UUID,
    target_soldier_id: uuid.UUID | None,
    reason: str | None,
    target_soldier_ids: list[uuid.UUID] | None = None,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest | list[SwapRequest]:
    """Create one or more targeted swap requests for the same duty assignment.

    `target_soldier_ids`, when given, takes precedence over `target_soldier_id`
    and fans out into one SwapRequest row per target (capped by the
    swaps.max_specific_targets setting). Single-target/open-board callers keep
    using `target_soldier_id` unmodified and get a single SwapRequest back.
    """
    if target_soldier_ids is not None and len(target_soldier_ids) == 0:
        raise SwapError("no_targets_specified")
    targets = target_soldier_ids if target_soldier_ids is not None else (
        [target_soldier_id] if target_soldier_id is not None else [None]
    )
    if len(targets) > _max_specific_targets(session):
        raise SwapError("too_many_targets")
    if len(targets) > 1:
        return [
            _create_single_request(
                session, requesting_soldier_id=requesting_soldier_id,
                duty_assignment_id=duty_assignment_id, target_soldier_id=t,
                reason=reason, actor_id=actor_id,
            )
            for t in targets
        ]
    return _create_single_request(
        session, requesting_soldier_id=requesting_soldier_id,
        duty_assignment_id=duty_assignment_id, target_soldier_id=targets[0],
        reason=reason, actor_id=actor_id,
    )


def _create_single_request(
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
        _enforce_hierarchy_level_restriction(
            session, requesting_soldier_id=requesting_soldier_id, other_soldier_id=target_soldier_id
        )
    existing = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == duty_assignment_id,
            SwapRequest.target_soldier_id == target_soldier_id,
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


def _require_duty_manager_approval(session: Session) -> bool:
    try:
        return bool(get_setting(session, "swaps.require_duty_manager_approval"))
    except SettingNotFound:
        return True  # safe default: require approval


def _has_decision(session: Session, request_id: uuid.UUID, side: str, kind: str, *, approved: bool) -> bool:
    return session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.approver_kind == kind,
            SwapManagerApproval.approved == approved,  # noqa: E712
        ).limit(1)
    ).first() is not None


def _all_approved(session: Session, req: SwapRequest) -> bool:
    """Both soldiers must have approved (auto-set on claim/cover_offer), and
    — for each (side, kind) whose LIVE chain is non-empty — at least one
    approved decision-log row must exist for that (side, kind). A (side,
    kind) with an empty live chain (no commander at all, duty-manager
    approval off, or no duty manager currently in scope) is vacuously
    satisfied. Live chain membership only gates NEW clicks and what's
    displayed as required — a decision already recorded stays valid even if
    the org changes afterward."""
    if not (req.requester_side_approved and req.covering_side_approved):
        return False
    require_dm = _require_duty_manager_approval(session)
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            return False
        if commander_chain_for_soldier(session, soldier_id) and not _has_decision(session, req.id, side, "commander", approved=True):
            return False
        if require_dm and duty_manager_chain_for_soldier(session, soldier_id) and not _has_decision(session, req.id, side, "duty_manager", approved=True):
            return False
    return True


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


def is_chain_commander_for_side(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID
) -> bool:
    """Is `commander_id` CURRENTLY (live) a required commander-in-scope or
    duty-manager-in-scope for this side — regardless of whether they've
    already approved. Used to route between the chain-member path
    (approve_manager_row) and the broader-authorization override path
    (approve_manager_side_override)."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        return False
    soldier_id = req.requesting_soldier_id if side == "requester" else req.covering_soldier_id
    if soldier_id is None:
        return False
    if commander_id in commander_chain_for_soldier(session, soldier_id):
        return True
    if _require_duty_manager_approval(session) and commander_id in duty_manager_chain_for_soldier(session, soldier_id):
        return True
    return False


def _qualifying_rows_for_actor(session: Session, req: SwapRequest, actor_id: uuid.UUID) -> list[tuple[str, str]]:
    """Every (side, kind) `actor_id` is CURRENTLY (live) a required approver
    for on this request — spans both sides and both kinds in one pass, so a
    single approve/reject call resolves everything this person is eligible
    for at once (same person commander of both soldiers, or duty-manager of
    both, or both roles for one or both soldiers — no special-casing)."""
    require_dm = _require_duty_manager_approval(session)
    out: list[tuple[str, str]] = []
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            continue
        if actor_id in commander_chain_for_soldier(session, soldier_id):
            out.append((side, "commander"))
        if require_dm and actor_id in duty_manager_chain_for_soldier(session, soldier_id):
            out.append((side, "duty_manager"))
    return out


def _get_or_create_row(session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID, kind: str) -> SwapManagerApproval:
    row = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == actor_id,
            SwapManagerApproval.approver_kind == kind,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SwapManagerApproval(swap_request_id=request_id, side=side, commander_id=actor_id, approver_kind=kind)
        session.add(row)
    return row


def approve_manager_row(session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID) -> SwapRequest:
    """Approve every (side, kind) row `actor_id` currently qualifies for on
    this request, in one call. Idempotent: rows already approved are left
    untouched (original approver/timestamp kept). Raises
    SwapError("not_required_approver") if `actor_id` doesn't currently
    qualify for anything on this request."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    qualifying = _qualifying_rows_for_actor(session, req, actor_id)
    if not qualifying:
        raise SwapError("not_required_approver")
    now = datetime.utcnow()
    for side, kind in qualifying:
        row = _get_or_create_row(session, request_id=request_id, side=side, actor_id=actor_id, kind=kind)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            write_audit(
                session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
                entity_id=req.id, after={"side": side, "kind": kind},
            )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def reject_manager_row(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID, decision_note: str | None = None,
) -> SwapRequest:
    """Stamp rejected on every (side, kind) row `actor_id` currently
    qualifies for on this request (if any), then kill the whole request via
    the existing reject_request path — same overall effect as today (any
    required approver rejecting still ends the swap immediately), now with
    per-row attribution for display. Permissive: if `actor_id` doesn't
    qualify for any specific row (e.g. a broader-authorization override
    actor, not a literal chain member), this simply skips row-stamping and
    still proceeds to reject_request — the route is responsible for having
    already authorized the caller before reaching this function."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    now = datetime.utcnow()
    for side, kind in _qualifying_rows_for_actor(session, req, actor_id):
        row = _get_or_create_row(session, request_id=request_id, side=side, actor_id=actor_id, kind=kind)
        if not row.rejected:
            row.rejected = True
            row.rejected_by = actor_id
            row.rejected_at = now
    session.flush()
    return reject_request(session, request_id=request_id, decision_note=decision_note, actor_id=actor_id)


def approve_manager_side(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID,
    is_authorized_override: Callable[[], bool] | bool,
) -> SwapRequest:
    """Shared entry point for "approve this side's manager requirement as
    actor_id", used by the manager-approve REST route, the Telegram bot
    action, and the notifications action-token dispatcher — the three of
    which previously duplicated this branching logic near-verbatim.

    If actor_id is a required chain commander for this side, approves their
    own row via approve_manager_row (idempotent if already approved).
    Otherwise, falls back to override authorization: is_authorized_override
    may be a plain bool the caller already computed, or a zero-arg callable
    deferred until it's actually needed (useful when computing/asserting
    authorization is itself the thing that would raise, e.g. a caller that
    wants to defer calling authorize() — which raises HTTPException on
    failure — until we've confirmed the actor isn't simply a chain commander).
    If authorized, clears the whole side via approve_manager_side_override.
    Raises SwapError("forbidden") if neither applies.
    """
    if is_chain_commander_for_side(session, request_id=request_id, side=side, commander_id=actor_id):
        return approve_manager_row(session, request_id=request_id, actor_id=actor_id)
    authorized = is_authorized_override() if callable(is_authorized_override) else is_authorized_override
    if not authorized:
        raise SwapError("forbidden")
    return approve_manager_side_override(session, request_id=request_id, side=side, actor_id=actor_id)


def approve_manager_side_override(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID
) -> SwapRequest:
    """Used when the acting user is authorized (admin / duty-manager / broader
    commander scope) but isn't literally one of the required chain
    commanders/duty-managers — inserts (or updates) an approved row for
    every LIVE-required kind on that side, attributed to actor_id, clearing
    the whole side's requirement at once."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    soldier_id = req.requesting_soldier_id if side == "requester" else req.covering_soldier_id
    if soldier_id is None:
        raise SwapError("no_soldier_for_side")
    kinds_needed = []
    if commander_chain_for_soldier(session, soldier_id):
        kinds_needed.append("commander")
    if _require_duty_manager_approval(session) and duty_manager_chain_for_soldier(session, soldier_id):
        kinds_needed.append("duty_manager")
    now = datetime.utcnow()
    cleared = 0
    for kind in kinds_needed:
        row = _get_or_create_row(session, request_id=request_id, side=side, actor_id=actor_id, kind=kind)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            cleared += 1
    write_audit(
        session, actor_id=actor_id, action="swap.manager_approve_override", entity_type="swap_request",
        entity_id=req.id, after={"side": side, "rows_cleared": cleared},
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
    _enforce_hierarchy_level_restriction(
        session,
        requesting_soldier_id=req.requesting_soldier_id,
        other_soldier_id=covering_soldier_id,
    )
    req.covering_soldier_id = covering_soldier_id
    before_status = req.status
    if _require_approval(session):
        req.status = "pending_approval"
        req.requester_side_approved = True   # asking already implied consent
        req.covering_side_approved = True    # covering (claiming) already implied consent
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
        create_notification(session, soldier_id=req.requesting_soldier_id,
                            type=NotificationType.swap_accepted,
                            title="בקשת ההחלפה בוצעה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
        create_notification(session, soldier_id=covering_soldier_id,
                            type=NotificationType.swap_accepted,
                            title="בקשת ההחלפה בוצעה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
        write_audit(
            session, actor_id=actor_id, action="swap.claim", entity_type="swap_request",
            entity_id=req.id, before={"status": before_status},
            after={"status": "applied", "covering_soldier_id": str(covering_soldier_id)},
        )
    session.flush()
    # This request is now claimed (targeted at a specific covering soldier).
    # If it was one of several parallel requests for the same duty +
    # requester — whether fanned out together by create_request or created
    # separately afterward — cancel the still-live siblings: the requester
    # only needs one cover, not N. "Still-live" mirrors cancel_request's own
    # notion of cancellable statuses (open or pending_approval) rather than
    # just "open", otherwise a sibling that already reached pending_approval
    # (its own claim in progress, awaiting manager approval) would never get
    # cancelled here, leaving two parallel flows able to both reach
    # _apply_cover for the same assignment.
    siblings = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == req.duty_assignment_id,
            SwapRequest.requesting_soldier_id == req.requesting_soldier_id,
            SwapRequest.id != req.id,
            SwapRequest.status.in_(["open", "pending_approval"]),
        )
    ).scalars().all()
    for sib in siblings:
        sib.status = "cancelled"
        if sib.covering_soldier_id is not None:
            create_notification(
                session, soldier_id=sib.covering_soldier_id,
                type=NotificationType.swap_rejected,
                title="בקשת ההחלפה בוטלה — כבר נמצא מחליף אחר",
                reference_type="swap_request", reference_id=sib.id,
                actor_id=actor_id,
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
    req.rejected_by = actor_id
    create_notification(session, soldier_id=req.requesting_soldier_id,
                        type=NotificationType.swap_rejected,
                        title="בקשת ההחלפה נדחתה",
                        reference_type="swap_request", reference_id=req.id,
                        actor_id=actor_id)
    if req.covering_soldier_id is not None:
        create_notification(session, soldier_id=req.covering_soldier_id,
                            type=NotificationType.swap_rejected,
                            title="בקשת ההחלפה נדחתה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="swap.reject", entity_type="swap_request",
        entity_id=req.id, before=before,
        after={"status": "rejected", "decision_note": decision_note, "rejected_by": str(actor_id) if actor_id else None},
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
    if req.covering_soldier_id is not None:
        create_notification(session, soldier_id=req.covering_soldier_id,
                            type=NotificationType.swap_rejected,
                            title="בקשת ההחלפה בוטלה ע\"י המבקש",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
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
    _enforce_hierarchy_level_restriction(
        session,
        requesting_soldier_id=assignment.soldier_id,
        other_soldier_id=covering_soldier_id,
    )

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
    _enforce_hierarchy_level_restriction(
        session,
        requesting_soldier_id=req.requesting_soldier_id,
        other_soldier_id=covering_soldier_id,
    )
    req.covering_soldier_id = covering_soldier_id
    req.offered_assignment_ids = [str(aid) for aid in offered_assignment_ids]

    if _require_approval(session):
        req.status = "pending_approval"
        req.requester_side_approved = True   # asking already implied consent
        req.covering_side_approved = True    # covering (claiming) already implied consent
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
        create_notification(
            session, soldier_id=req.requesting_soldier_id,
            type=NotificationType.swap_accepted,
            title="בקשת ההחלפה בוצעה",
            reference_type="swap_request", reference_id=req.id,
            actor_id=actor_id,
        )
        create_notification(
            session, soldier_id=covering_soldier_id,
            type=NotificationType.swap_accepted,
            title="בקשת ההחלפה בוצעה",
            reference_type="swap_request", reference_id=req.id,
            actor_id=actor_id,
        )

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
