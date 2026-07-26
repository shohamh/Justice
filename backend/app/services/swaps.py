from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment, HierarchyNode, NotificationType, Soldier, SwapCandidate, SwapManagerApproval, SwapRequest,
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
    open_to_marketplace: bool = False,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    """Create (or extend) the one open SwapRequest for this (requester, duty),
    with a SwapCandidate row per invited target plus optional marketplace
    visibility. Always returns a single SwapRequest — no more fan-out into
    multiple parent rows."""
    targets = target_soldier_ids if target_soldier_ids is not None else (
        [target_soldier_id] if target_soldier_id is not None else []
    )
    if len(targets) > _max_specific_targets(session):
        raise SwapError("too_many_targets")
    if not targets and not open_to_marketplace:
        raise SwapError("no_targets_specified")

    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    if assignment.soldier_id != requesting_soldier_id:
        raise SwapError("not_your_duty")
    if assignment.status != "published":
        raise SwapError("not_published")

    existing = session.execute(
        select(SwapRequest).where(
            SwapRequest.duty_assignment_id == duty_assignment_id,
            SwapRequest.requesting_soldier_id == requesting_soldier_id,
            SwapRequest.status == "open",
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise SwapError("already_pending")

    req = SwapRequest(
        duty_assignment_id=duty_assignment_id,
        duty_date=assignment.start_date,
        requesting_soldier_id=requesting_soldier_id,
        reason=reason,
        status="open",
        open_to_marketplace=open_to_marketplace,
    )
    session.add(req)
    try:
        session.flush()
    except IntegrityError:
        # Two concurrent create_request calls for the same (requester, duty)
        # can both pass the SELECT check above before either commits; the
        # partial unique index uq_swap_requests_one_open_per_requester_duty
        # is the real backstop and raises here for whichever insert loses
        # the race. Translate it to the same domain error the SELECT-based
        # check raises so callers see one consistent error either way.
        session.rollback()
        raise SwapError("already_pending") from None

    for target_id in targets:
        _add_invited_candidate(
            session, req=req, requesting_soldier_id=requesting_soldier_id,
            target_soldier_id=target_id, actor_id=actor_id,
        )

    write_audit(
        session, actor_id=actor_id, action="swap.create", entity_type="swap_request",
        entity_id=req.id,
        after={
            "duty_assignment_id": str(duty_assignment_id),
            "duty_date": req.duty_date.isoformat(),
            "target_soldier_ids": [str(t) for t in targets],
            "open_to_marketplace": open_to_marketplace,
            "status": "open",
        },
    )
    session.flush()
    return req


def _add_invited_candidate(
    session: Session, *, req: SwapRequest, requesting_soldier_id: uuid.UUID,
    target_soldier_id: uuid.UUID, actor_id: uuid.UUID | None,
) -> SwapCandidate:
    if target_soldier_id == requesting_soldier_id:
        raise SwapError("cannot_target_self")
    eligible, reason = check_soldier_for_assignment(session, target_soldier_id, req.duty_assignment_id)
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
    _enforce_hierarchy_level_restriction(
        session, requesting_soldier_id=requesting_soldier_id, other_soldier_id=target_soldier_id
    )
    candidate = SwapCandidate(swap_request_id=req.id, soldier_id=target_soldier_id, source="invited")
    session.add(candidate)
    session.flush()
    create_notification(
        session, soldier_id=target_soldier_id, type=NotificationType.swap_offer_incoming,
        title="הגיעה בקשת החלפה עבורך", reference_type="swap_request", reference_id=req.id,
        actor_id=actor_id,
    )
    return candidate


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
    # TODO(Task 4): rewritten there to finalize per-candidate (race-safe,
    # first-fully-approved-candidate-wins) against the new SwapCandidate
    # shape. The pre-Task-1 body below referenced req.covering_soldier_id /
    # req.covering_side_approved, which no longer exist on SwapRequest — that
    # rewrite is explicitly Task 4's job, not this task's. Stubbed to a
    # no-op for now so create_request/claim_request (this task's scope) can
    # be tested in isolation without a half-finished finalize path.
    return


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


def _override_authorized_kinds(
    session: Session, *, actor_id: uuid.UUID, side_node: HierarchyNode | None
) -> set[str]:
    """Which approver kinds `actor_id` may clear via the override path for a
    side whose soldier belongs to `side_node`.

    An override only satisfies the kind(s) the actor actually holds authority
    for: a commander with broad hierarchy scope (but no chain row of their
    own, e.g. reassigned to the node after the swap was claimed) may clear
    the commander requirement, but must not silently satisfy the separate
    duty-manager requirement — and vice versa. Only admins clear both."""
    from app.auth.authz import _node_in_scope, is_commander, is_duty_manager, scope_root_ids

    actor = session.get(Soldier, actor_id)
    if actor is not None and actor.role == "admin":
        return {"commander", "duty_manager"}
    kinds: set[str] = set()
    if is_duty_manager(session, actor_id):
        kinds.add("duty_manager")
    if actor is not None and is_commander(session, actor_id):
        if _node_in_scope(side_node, scope_root_ids(session, actor)):
            kinds.add("commander")
    return kinds


def approve_manager_side_override(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID
) -> SwapRequest:
    """Used when the acting user is authorized (admin / duty-manager / broader
    commander scope) but isn't literally one of the required chain
    commanders/duty-managers — inserts (or updates) an approved row for every
    LIVE-required kind on that side THAT THE ACTOR IS AUTHORIZED FOR (see
    `_override_authorized_kinds`: a commander overriding must not also
    silently satisfy a separate duty-manager requirement, and vice versa —
    only admins clear both), attributed to actor_id."""
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    soldier_id = req.requesting_soldier_id if side == "requester" else req.covering_soldier_id
    if soldier_id is None:
        raise SwapError("no_soldier_for_side")
    side_node = None
    soldier = session.get(Soldier, soldier_id)
    if soldier is not None and soldier.hierarchy_node_id is not None:
        side_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    allowed_kinds = _override_authorized_kinds(session, actor_id=actor_id, side_node=side_node)
    if not allowed_kinds:
        raise SwapError("forbidden")
    kinds_needed = []
    if commander_chain_for_soldier(session, soldier_id):
        kinds_needed.append("commander")
    if _require_duty_manager_approval(session) and duty_manager_chain_for_soldier(session, soldier_id):
        kinds_needed.append("duty_manager")
    kinds_to_clear = [k for k in kinds_needed if k in allowed_kinds]
    now = datetime.utcnow()
    cleared = 0
    for kind in kinds_to_clear:
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
    if session.get(Soldier, covering_soldier_id) is None:
        raise SwapError("soldier_not_found")

    existing_candidate = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.soldier_id == covering_soldier_id,
        )
    ).scalar_one_or_none()

    if existing_candidate is None:
        if not req.open_to_marketplace:
            raise SwapError("not_targeted_at_you")
        eligible, reason = check_soldier_for_assignment(session, covering_soldier_id, req.duty_assignment_id)
        if not eligible:
            raise SwapError(f"cover_not_eligible:{reason}")
        _enforce_hierarchy_level_restriction(
            session, requesting_soldier_id=req.requesting_soldier_id, other_soldier_id=covering_soldier_id,
        )
        candidate = SwapCandidate(swap_request_id=request_id, soldier_id=covering_soldier_id, source="marketplace")
        session.add(candidate)
    else:
        if existing_candidate.status not in ("pending",):
            raise SwapError("already_pending")
        candidate = existing_candidate

    before_status = candidate.status
    candidate.status = "accepted"
    candidate.soldier_side_approved = True
    req.requester_side_approved = True  # asking already implied consent
    write_audit(
        session, actor_id=actor_id, action="swap.claim", entity_type="swap_request",
        entity_id=req.id, before={"candidate_status": before_status},
        after={"candidate_status": "accepted", "soldier_id": str(covering_soldier_id)},
    )
    create_notification(
        session, soldier_id=req.requesting_soldier_id, type=NotificationType.swap_offer,
        title="הייתה הצעת החלפה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    session.flush()
    _try_finalize(session, req, actor_id)
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
