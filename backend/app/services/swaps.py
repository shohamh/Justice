from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Callable

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
        _enforce_hierarchy_level_restriction(
            session, requesting_soldier_id=requesting_soldier_id, other_soldier_id=target_soldier_id
        )
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


def _require_duty_manager_approval(session: Session) -> bool:
    try:
        return bool(get_setting(session, "swaps.require_duty_manager_approval"))
    except SettingNotFound:
        return True  # safe default: require approval


def duty_manager_ids(session: Session) -> list[uuid.UUID]:
    return list(session.execute(select(Soldier.id).where(Soldier.role == "duty_manager")).scalars().all())


def commander_chain_for_soldier(session: Session, soldier_id: uuid.UUID) -> list[uuid.UUID]:
    """Every distinct commander from the soldier's own node up to the root of
    the hierarchy, excluding the soldier themself if they command their own node.

    Ordered NEAREST-commander-first: chain[0] is the closest ancestor (or the
    soldier's own node) that has a commander, and the list walks outward to
    the root from there. `node.path_ids` is materialized root-first (see
    `hierarchy.py`: `node.path_ids = [*parent.path_ids, node.id]`), so we
    reorder via `reversed(node.path_ids)` rather than relying on the `IN (...)`
    query's row order, which SQL does not guarantee to match the list order.
    """
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return []
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None or not node.path_ids:
        return []
    nodes_by_id = {
        n.id: n
        for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(node.path_ids))
        ).scalars().all()
    }
    seen: set[uuid.UUID] = set()
    chain: list[uuid.UUID] = []
    for node_id in reversed(node.path_ids):
        n = nodes_by_id.get(node_id)
        if n is None:
            continue
        if n.commander_id and n.commander_id != soldier_id and n.commander_id not in seen:
            seen.add(n.commander_id)
            chain.append(n.commander_id)
    return chain


def _create_manager_approval_rows(session: Session, *, req: SwapRequest) -> None:
    """Populate swap_manager_approvals for both sides: one row per chain
    commander, plus (if swaps.require_duty_manager_approval) one row per
    duty manager. Called once, when a swap enters pending_approval with a
    known covering soldier."""
    dm_ids = duty_manager_ids(session) if _require_duty_manager_approval(session) else []
    for side, soldier_id in (("requester", req.requesting_soldier_id), ("covering", req.covering_soldier_id)):
        if soldier_id is None:
            continue
        for idx, commander_id in enumerate(commander_chain_for_soldier(session, soldier_id)):
            session.add(SwapManagerApproval(
                swap_request_id=req.id, side=side, commander_id=commander_id,
                chain_order=idx, approver_kind="commander",
            ))
        for idx, dm_id in enumerate(dm_ids):
            session.add(SwapManagerApproval(
                swap_request_id=req.id, side=side, commander_id=dm_id,
                chain_order=idx, approver_kind="duty_manager",
            ))
    session.flush()


def _all_approved(session: Session, req: SwapRequest) -> bool:
    """Both soldiers must have approved, and — for each (side, approver_kind)
    combination that has at least one required row — at least one of that
    combination's rows must be approved (any single required approver of
    that kind suffices; a combination with zero rows is trivially satisfied,
    e.g. no duty manager exists, or a side has no commander in its chain)."""
    if not (req.requester_side_approved and req.covering_side_approved):
        return False
    for side in ("requester", "covering"):
        for kind in ("commander", "duty_manager"):
            has_rows = session.execute(
                select(SwapManagerApproval.id).where(
                    SwapManagerApproval.swap_request_id == req.id,
                    SwapManagerApproval.side == side,
                    SwapManagerApproval.approver_kind == kind,
                ).limit(1)
            ).first()
            if has_rows is None:
                continue
            has_approved = session.execute(
                select(SwapManagerApproval.id).where(
                    SwapManagerApproval.swap_request_id == req.id,
                    SwapManagerApproval.side == side,
                    SwapManagerApproval.approver_kind == kind,
                    SwapManagerApproval.approved == True,  # noqa: E712
                ).limit(1)
            ).first()
            if has_approved is None:
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
    """Is `commander_id` one of the required chain commanders for this side at
    all — regardless of whether they've already approved. (Answers "is this
    person in the chain", not "...and haven't they approved yet" — a commander
    who already approved is still a chain commander, so a second click stays
    on the idempotent chain-approval path instead of rerouting into the
    override path meant for people outside the chain.)"""
    return session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == commander_id,
        )
    ).first() is not None


def approve_manager_row(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID, actor_id: uuid.UUID
) -> SwapRequest:
    """Approve `commander_id`'s own row for this side. Idempotent: if the row
    is already approved (e.g. this same commander clicking approve twice),
    this is a harmless no-op — the original approver/timestamp are kept, but
    _try_finalize still runs in case the swap wasn't finalized yet for some
    other reason (e.g. the other side just approved). Raises
    SwapError("not_required_approver") only if there is no row at all for
    (request_id, side, commander_id) — i.e. this person isn't in the chain.

    This lookup does not filter by approver_kind, so it would raise
    MultipleResultsFound if the same person ever held both a "commander" row
    and a "duty_manager" row for the same (request_id, side). That can't
    happen today: _create_manager_approval_rows sources commander rows from
    commander_chain_for_soldier (HierarchyNode.commander_id) and duty_manager
    rows from duty_manager_ids (Soldier.role == "duty_manager"), and
    recompute_role() (app/services/dm_scope.py) gives commander priority over
    duty_manager — is_commander() being true forces role="commander", which
    duty_manager_ids() excludes. So the two ID sets are always disjoint as
    long as role stays in sync, which recompute_role is called to maintain
    whenever chain/scope assignments change."""
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
        )
    ).scalar_one_or_none()
    if row is None:
        raise SwapError("not_required_approver")
    if not row.approved:
        row.approved = True
        row.approved_by = actor_id
        row.approved_at = datetime.utcnow()
        write_audit(
            session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
            entity_id=req.id, after={"side": side, "commander_id": str(commander_id)},
        )
        # Same person may be the required approver for both sides at once
        # (one commander over both soldiers, or the org's one duty manager)
        # — approving once should satisfy both sides instead of asking for
        # a second click. Filtered by approver_kind == row.approver_kind:
        # same reasoning as the primary `row` lookup above (commander vs.
        # duty_manager ID sets are disjoint via role priority, so this is
        # not reachable today either) — but `row.approver_kind` is already
        # in hand here for free, so filtering by it costs nothing and keeps
        # this cascade explicitly scoped to "same kind of requirement" by
        # construction rather than by an invariant living elsewhere.
        other_side = "covering" if side == "requester" else "requester"
        other_row = session.execute(
            select(SwapManagerApproval).where(
                SwapManagerApproval.swap_request_id == request_id,
                SwapManagerApproval.side == other_side,
                SwapManagerApproval.commander_id == commander_id,
                SwapManagerApproval.approver_kind == row.approver_kind,
                SwapManagerApproval.approved == False,  # noqa: E712
            )
        ).scalar_one_or_none()
        if other_row is not None:
            other_row.approved = True
            other_row.approved_by = actor_id
            other_row.approved_at = row.approved_at
            write_audit(
                session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
                entity_id=req.id, after={"side": other_side, "commander_id": str(commander_id), "cascaded": True},
            )
        session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


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
        return approve_manager_row(
            session, request_id=request_id, side=side, commander_id=actor_id, actor_id=actor_id
        )
    authorized = is_authorized_override() if callable(is_authorized_override) else is_authorized_override
    if not authorized:
        raise SwapError("forbidden")
    return approve_manager_side_override(session, request_id=request_id, side=side, actor_id=actor_id)


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
    _enforce_hierarchy_level_restriction(
        session,
        requesting_soldier_id=req.requesting_soldier_id,
        other_soldier_id=covering_soldier_id,
    )
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
    if req.covering_soldier_id is not None:
        create_notification(session, soldier_id=req.covering_soldier_id,
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
