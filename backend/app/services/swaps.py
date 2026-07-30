from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import select
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
    """Create the one open SwapRequest for this (requester, duty), with a
    SwapCandidate row per invited target plus optional marketplace
    visibility. Raises SwapError("already_pending") if an open request for
    this (requester, duty) already exists — always returns a single
    SwapRequest, no more fan-out into multiple parent rows."""
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


def add_targets(
    session: Session, *, request_id: uuid.UUID, target_soldier_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    """Invite additional specific soldiers on an already-open SwapRequest,
    on top of whoever was invited at creation or in a previous call. The
    running total of invited candidates (any status) still counts against
    swaps.max_specific_targets. Raises SwapError("not_open") if the request
    is no longer open, SwapError("target_limit_reached") if the total would
    exceed the cap, or SwapError(f"already_invited:{soldier_id}") if any
    target already has a SwapCandidate row on this request (any status) —
    checked both against existing rows and against duplicates within this
    same call."""
    # Unlike create_request, we don't need to translate a unique-constraint
    # IntegrityError from a concurrent duplicate-invite race here: _lock_request
    # takes SELECT ... FOR UPDATE on the parent request before we check for
    # existing candidates, so concurrent add_targets calls on the same request
    # are serialized and can never race past this point together. Don't remove
    # the lock, and don't add duplicate-error handling below "to be safe" —
    # it would be dead code.
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_open")

    existing_candidates = session.execute(
        select(SwapCandidate).where(SwapCandidate.swap_request_id == request_id)
    ).scalars().all()
    existing_soldier_ids = {c.soldier_id for c in existing_candidates}

    seen_this_call: set[uuid.UUID] = set()
    for target_id in target_soldier_ids:
        if target_id in existing_soldier_ids or target_id in seen_this_call:
            raise SwapError(f"already_invited:{target_id}")
        seen_this_call.add(target_id)

    if len(existing_candidates) + len(target_soldier_ids) > _max_specific_targets(session):
        raise SwapError("target_limit_reached")

    for target_id in target_soldier_ids:
        _add_invited_candidate(
            session, req=req, requesting_soldier_id=req.requesting_soldier_id,
            target_soldier_id=target_id, actor_id=actor_id,
        )

    write_audit(
        session, actor_id=actor_id, action="swap.add_targets", entity_type="swap_request",
        entity_id=req.id, after={"target_soldier_ids": [str(t) for t in target_soldier_ids]},
    )
    session.flush()
    return req


def publish_to_marketplace(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    """Flip open_to_marketplace on an already-open SwapRequest that wasn't
    published at creation time. Raises SwapError("not_open") if the request
    is no longer open, or SwapError("already_on_marketplace") if it's
    already published."""
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_open")
    if req.open_to_marketplace:
        raise SwapError("already_on_marketplace")
    req.open_to_marketplace = True
    write_audit(
        session, actor_id=actor_id, action="swap.publish", entity_type="swap_request",
        entity_id=req.id, after={"open_to_marketplace": True},
    )
    session.flush()
    return req


def list_open_board(session: Session, *, for_soldier_id: uuid.UUID) -> list[SwapRequest]:
    """Open postings visible to a soldier: marketplace-visible, excluding
    their own requests and ones they're already a candidate on."""
    already_candidate_on = session.execute(
        select(SwapCandidate.swap_request_id).where(SwapCandidate.soldier_id == for_soldier_id)
    ).scalars().all()
    return list(
        session.execute(
            select(SwapRequest)
            .where(
                SwapRequest.status == "open",
                SwapRequest.requesting_soldier_id != for_soldier_id,
                SwapRequest.open_to_marketplace.is_(True),
                SwapRequest.id.notin_(already_candidate_on) if already_candidate_on else True,
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


def _has_decision(session: Session, request_id: uuid.UUID, candidate_id: uuid.UUID | None, side: str, kind: str, *, approved: bool) -> bool:
    return session.execute(
        select(SwapManagerApproval.id).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.swap_candidate_id == candidate_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.approver_kind == kind,
            SwapManagerApproval.approved == approved,  # noqa: E712
        ).limit(1)
    ).first() is not None


def _lock_request(session: Session, request_id: uuid.UUID) -> SwapRequest | None:
    """Fetch a SwapRequest with SELECT ... FOR UPDATE.

    Every mutating entry point takes this lock as its FIRST database
    interaction, so that concurrent transactions touching the same request
    serialize on it. Two things depend on that placement:

    * Correctness — `_try_finalize` must not be able to run twice for the same
      request. Without serialization two commanders clearing the last approval
      on two different candidates at the same moment both read status='open',
      both pick a winner, and both call `_apply_cover`; duty_day_overrides has
      no unique constraint on (duty_assignment_id, date), so that silently
      writes two conflicting override rows for the same day.
    * Deadlock avoidance — inserting a SwapManagerApproval (or any child row)
      takes a FOR KEY SHARE lock on the parent swap_requests row via the
      foreign key. FOR KEY SHARE is shared, so two transactions both get it;
      if each then tried to UPGRADE to FOR UPDATE they would wait on each
      other and Postgres would kill one with a deadlock. Taking the exclusive
      lock up front, before any child insert, removes the upgrade entirely.

    populate_existing refreshes the identity-mapped instance from the row as
    it exists once the lock is held, so callers never act on a stale read of a
    request another transaction just finalized.
    """
    return session.execute(
        select(SwapRequest)
        .where(SwapRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _candidate_fully_approved(session: Session, req: SwapRequest, candidate: SwapCandidate) -> bool:
    """A candidate is ready to finalize once: the requester has approved
    (shared across all candidates), this candidate has approved, and — only
    when manager approval is configured as required at all
    (`swaps.require_manager_approval`) — both sides' live commander/duty-
    manager chains (if any) have an approved decision row. When manager
    approval isn't required, the two soldier-side confirmations alone are
    sufficient (matches today's `not _require_approval` bypass in the old
    claim_request)."""
    if not (req.requester_side_approved and candidate.soldier_side_approved):
        return False
    if not _require_approval(session):
        return True
    require_dm = _require_duty_manager_approval(session)
    if commander_chain_for_soldier(session, req.requesting_soldier_id) and not _has_decision(session, req.id, None, "requester", "commander", approved=True):
        return False
    if require_dm and duty_manager_chain_for_soldier(session, req.requesting_soldier_id) and not _has_decision(session, req.id, None, "requester", "duty_manager", approved=True):
        return False
    if commander_chain_for_soldier(session, candidate.soldier_id) and not _has_decision(session, req.id, candidate.id, "covering", "commander", approved=True):
        return False
    if require_dm and duty_manager_chain_for_soldier(session, candidate.soldier_id) and not _has_decision(session, req.id, candidate.id, "covering", "duty_manager", approved=True):
        return False
    return True


def _try_finalize(session: Session, req: SwapRequest, actor_id: uuid.UUID | None) -> None:
    """Race: check every live (pending/accepted) candidate; the first one
    found fully approved wins — applies the cover, marks the request
    applied, and cancels every other still-live candidate. Candidates are
    checked in creation order so ties resolve deterministically (earliest
    invited/claimed wins). Runs the same regardless of the
    require-manager-approval setting — `_candidate_fully_approved` is what
    varies its bar based on that setting, not this function.

    Concurrency: this is only ever reached with the parent SwapRequest row
    already exclusively locked — every caller goes through `_lock_request`
    before touching anything (see its docstring for why the lock has to be
    taken that early rather than here). The re-lock below is therefore a
    no-op re-entry on a lock this transaction already holds; it's kept so the
    invariant still holds if a future caller forgets, and so the status check
    is made against the row as it exists under the lock."""
    locked = _lock_request(session, req.id)
    if locked is None or locked.status != "open":
        return
    candidates = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == req.id,
            SwapCandidate.status.in_(["pending", "accepted"]),
        ).order_by(SwapCandidate.created_at.asc())
    ).scalars().all()
    winner = next((c for c in candidates if _candidate_fully_approved(session, req, c)), None)
    if winner is None:
        return
    _apply_cover(session, req=req, candidate=winner, actor_id=actor_id)
    winner.status = "applied"
    winner.decided_at = datetime.utcnow()
    req.status = "applied"
    create_notification(
        session, soldier_id=req.requesting_soldier_id, type=NotificationType.swap_accepted,
        title="בקשת ההחלפה בוצעה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    create_notification(
        session, soldier_id=winner.soldier_id, type=NotificationType.swap_accepted,
        title="בקשת ההחלפה בוצעה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    for other in candidates:
        if other.id == winner.id:
            continue
        other.status = "cancelled"
        other.decided_at = datetime.utcnow()
        create_notification(
            session, soldier_id=other.soldier_id, type=NotificationType.swap_rejected,
            title="בקשת ההחלפה בוטלה — כבר נמצא מחליף אחר", reference_type="swap_request",
            reference_id=req.id, actor_id=actor_id,
        )
    write_audit(
        session, actor_id=actor_id, action="swap.finalize", entity_type="swap_request",
        entity_id=req.id, after={"winning_candidate_id": str(winner.id), "soldier_id": str(winner.soldier_id)},
    )


def decline_candidate(
    session: Session, *, request_id: uuid.UUID, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None,
) -> SwapCandidate:
    """A candidate soldier declines their own invite/claim — only removes
    them from contention, never touches the parent request or other
    candidates."""
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    candidate = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.soldier_id == soldier_id,
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise SwapError("not_a_party")
    if candidate.status not in ("pending", "accepted"):
        raise SwapError("not_pending")
    candidate.status = "declined"
    candidate.decided_at = datetime.utcnow()
    write_audit(
        session, actor_id=actor_id or soldier_id, action="swap.candidate_decline",
        entity_type="swap_request", entity_id=request_id, after={"soldier_id": str(soldier_id)},
    )
    session.flush()
    return candidate


def approve_soldier_side(
    session: Session, *, request_id: uuid.UUID, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> SwapRequest:
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if soldier_id == req.requesting_soldier_id:
        if req.status == "applied":
            # The request may have already finalized (a different candidate
            # won the race) by the time this lands — a late requester-side
            # approval in that case is a harmless no-op, not an error.
            return req
        if req.status != "open":
            raise SwapError("not_pending")
        req.requester_side_approved = True
        write_audit(
            session, actor_id=actor_id or soldier_id, action="swap.soldier_approve",
            entity_type="swap_request", entity_id=req.id, after={"soldier_id": str(soldier_id), "side": "requester"},
        )
        session.flush()
        _try_finalize(session, req, actor_id or soldier_id)
        session.flush()
        return req
    candidate = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.soldier_id == soldier_id,
        )
    ).scalar_one_or_none()
    if candidate is None:
        raise SwapError("not_a_party")
    if candidate.status not in ("pending", "accepted"):
        # Already resolved — applied (won), cancelled (lost the finalize
        # race to another candidate), or declined. A late approval call
        # arriving after the race has already settled this candidate is a
        # harmless no-op rather than an error.
        return req
    if req.status != "open":
        raise SwapError("not_pending")
    candidate.soldier_side_approved = True
    if candidate.status == "pending":
        candidate.status = "accepted"
    if candidate.source == "invited":
        # The requester specifically invited this soldier, so inviting them
        # already implies the requester's consent to swap with them —
        # consistent with claim_request/cover_offer's auto-approval for
        # invited candidates. Marketplace-claimed candidates are NOT covered
        # here: the requester never chose them, so their separate approval
        # must still be obtained.
        req.requester_side_approved = True
    write_audit(
        session, actor_id=actor_id or soldier_id, action="swap.soldier_approve",
        entity_type="swap_request", entity_id=req.id,
        after={"soldier_id": str(soldier_id), "side": "covering", "candidate_id": str(candidate.id)},
    )
    session.flush()
    _try_finalize(session, req, actor_id or soldier_id)
    session.flush()
    return req


def _get_candidate_for_request(
    session: Session, request_id: uuid.UUID, candidate_id: uuid.UUID | None,
) -> SwapCandidate | None:
    """Fetch `candidate_id`, verifying it actually belongs to `request_id`.
    Raises SwapError("candidate_mismatch") if a caller passes a candidate that
    belongs to a different swap request than the one it's paired with."""
    if candidate_id is None:
        return None
    candidate = session.get(SwapCandidate, candidate_id)
    if candidate is not None and candidate.swap_request_id != request_id:
        raise SwapError("candidate_mismatch")
    return candidate


def is_chain_commander_for_side(
    session: Session, *, request_id: uuid.UUID, side: str, commander_id: uuid.UUID, candidate_id: uuid.UUID | None = None,
) -> bool:
    req = session.get(SwapRequest, request_id)
    if req is None:
        return False
    if side == "requester":
        soldier_id = req.requesting_soldier_id
    else:
        if candidate_id is None:
            return False
        candidate = _get_candidate_for_request(session, request_id, candidate_id)
        soldier_id = candidate.soldier_id if candidate else None
    if soldier_id is None:
        return False
    if commander_id in commander_chain_for_soldier(session, soldier_id):
        return True
    if _require_duty_manager_approval(session) and commander_id in duty_manager_chain_for_soldier(session, soldier_id):
        return True
    return False


def _qualifying_rows_for_actor(
    session: Session, req: SwapRequest, actor_id: uuid.UUID, candidate_id: uuid.UUID | None,
) -> list[tuple[str, str]]:
    """Every (side, kind) `actor_id` is CURRENTLY a required approver for on
    this request — requester side always checked; covering side only if
    `candidate_id` is given (a manager acts on one candidate at a time)."""
    require_dm = _require_duty_manager_approval(session)
    out: list[tuple[str, str]] = []
    if actor_id in commander_chain_for_soldier(session, req.requesting_soldier_id):
        out.append(("requester", "commander"))
    if require_dm and actor_id in duty_manager_chain_for_soldier(session, req.requesting_soldier_id):
        out.append(("requester", "duty_manager"))
    if candidate_id is not None:
        candidate = _get_candidate_for_request(session, req.id, candidate_id)
        if candidate is not None:
            if actor_id in commander_chain_for_soldier(session, candidate.soldier_id):
                out.append(("covering", "commander"))
            if require_dm and actor_id in duty_manager_chain_for_soldier(session, candidate.soldier_id):
                out.append(("covering", "duty_manager"))
    return out


def _get_or_create_row(
    session: Session, *, request_id: uuid.UUID, candidate_id: uuid.UUID | None, side: str, actor_id: uuid.UUID, kind: str,
) -> SwapManagerApproval:
    row = session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == request_id,
            SwapManagerApproval.swap_candidate_id == candidate_id,
            SwapManagerApproval.side == side,
            SwapManagerApproval.commander_id == actor_id,
            SwapManagerApproval.approver_kind == kind,
        )
    ).scalar_one_or_none()
    if row is None:
        row = SwapManagerApproval(
            swap_request_id=request_id, swap_candidate_id=candidate_id, side=side, commander_id=actor_id, approver_kind=kind,
        )
        session.add(row)
    return row


def approve_manager_row(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID, candidate_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_pending")
    qualifying = _qualifying_rows_for_actor(session, req, actor_id, candidate_id)
    if not qualifying:
        raise SwapError("not_required_approver")
    now = datetime.utcnow()
    for side, kind in qualifying:
        row_candidate_id = candidate_id if side == "covering" else None
        row = _get_or_create_row(session, request_id=request_id, candidate_id=row_candidate_id, side=side, actor_id=actor_id, kind=kind)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            write_audit(
                session, actor_id=actor_id, action="swap.manager_approve", entity_type="swap_request",
                entity_id=req.id, after={"side": side, "kind": kind, "candidate_id": str(candidate_id) if candidate_id else None},
            )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def reject_manager_row(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID, candidate_id: uuid.UUID | None = None,
    decision_note: str | None = None,
    is_authorized_override: "Callable[[], bool] | bool" = False,
) -> SwapRequest:
    """Stamps rejected on every (side, kind) row the actor qualifies for, then
    resolves the rejection at the scope the CALLER asked for:

    * `candidate_id is None` — a whole-request rejection. Only reachable from
      the UI's separate "reject the whole request" control, and only stamps
      requester-side rows (the covering side is never resolvable without a
      candidate). Kills the request via `reject_request`, cascading to cancel
      every live candidate.
    * `candidate_id is not None` — a per-candidate rejection. Only that
      candidate's covering-side rows are stamped and only that candidate is
      cancelled; the parent request and any sibling candidates are untouched.
      Requester-side qualification is deliberately IGNORED here: a duty
      manager or ancestor commander scoped over the requester's whole unit is
      very commonly also in a candidate's chain, and letting that requester-
      side qualification escalate would silently turn "reject candidate A"
      into "kill the whole request and every other candidate".

    `is_authorized_override` mirrors `approve_manager_side`'s override
    parameter: when the actor holds no qualifying chain row but the caller
    (the route) has already authorized them by a broader check — an admin, or
    a commander whose authority comes from hierarchy scope rather than chain
    membership — the rejection proceeds without stamping a chain row it has
    no business stamping, instead of failing with `not_required_approver`.
    Callers that don't pass it keep the strict behaviour (a genuine stranger
    still raises)."""
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_pending")
    qualifying = _qualifying_rows_for_actor(session, req, actor_id, candidate_id)
    if candidate_id is not None:
        qualifying = [(side, kind) for side, kind in qualifying if side == "covering"]
    if not qualifying:
        authorized = is_authorized_override() if callable(is_authorized_override) else bool(is_authorized_override)
        if not authorized:
            raise SwapError("not_required_approver")
    now = datetime.utcnow()
    for side, kind in qualifying:
        row_candidate_id = candidate_id if side == "covering" else None
        row = _get_or_create_row(session, request_id=request_id, candidate_id=row_candidate_id, side=side, actor_id=actor_id, kind=kind)
        if not row.rejected:
            row.rejected = True
            row.rejected_by = actor_id
            row.rejected_at = now
    session.flush()
    if candidate_id is None:
        return reject_request(session, request_id=request_id, decision_note=decision_note, actor_id=actor_id)
    candidate = _get_candidate_for_request(session, request_id, candidate_id)
    if candidate is not None and candidate.status in ("pending", "accepted"):
        candidate.status = "cancelled"
        candidate.decided_at = now
        create_notification(
            session, soldier_id=candidate.soldier_id, type=NotificationType.swap_rejected,
            title="בקשת ההחלפה נדחתה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
        )
    session.flush()
    return req


def approve_manager_side(
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID,
    is_authorized_override: "Callable[[], bool] | bool",
    candidate_id: uuid.UUID | None = None,
) -> SwapRequest:
    if is_chain_commander_for_side(session, request_id=request_id, side=side, commander_id=actor_id, candidate_id=candidate_id):
        return approve_manager_row(session, request_id=request_id, actor_id=actor_id, candidate_id=candidate_id)
    authorized = is_authorized_override() if callable(is_authorized_override) else is_authorized_override
    if not authorized:
        raise SwapError("forbidden")
    return approve_manager_side_override(session, request_id=request_id, side=side, actor_id=actor_id, candidate_id=candidate_id)


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
    session: Session, *, request_id: uuid.UUID, side: str, actor_id: uuid.UUID, candidate_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_pending")
    if side == "requester":
        soldier_id = req.requesting_soldier_id
    else:
        if candidate_id is None:
            raise SwapError("no_soldier_for_side")
        candidate = _get_candidate_for_request(session, request_id, candidate_id)
        soldier_id = candidate.soldier_id if candidate else None
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
    row_candidate_id = candidate_id if side == "covering" else None
    for kind in kinds_to_clear:
        row = _get_or_create_row(session, request_id=request_id, candidate_id=row_candidate_id, side=side, actor_id=actor_id, kind=kind)
        if not row.approved:
            row.approved = True
            row.approved_by = actor_id
            row.approved_at = now
            cleared += 1
    write_audit(
        session, actor_id=actor_id, action="swap.manager_approve_override", entity_type="swap_request",
        entity_id=req.id, after={"side": side, "rows_cleared": cleared, "candidate_id": str(candidate_id) if candidate_id else None},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def _apply_cover(
    session: Session, *, req: SwapRequest, candidate: SwapCandidate, actor_id: uuid.UUID | None
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
                session, assignment=assignment, date=current,
                effective_soldier_id=candidate.soldier_id, reason="replacement", actor_id=actor_id,
            )
        except assignments_svc.AssignmentError as exc:
            raise SwapError(f"cover_blocked:{exc}") from exc
        if first_ov is None:
            first_ov = ov
        current += timedelta(days=1)
    req.resulting_override_id = first_ov.id if first_ov else None


def claim_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    covering_soldier_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = _lock_request(session, request_id)
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
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_rejectable")
    before = {"status": req.status}
    req.status = "rejected"
    req.decision_note = decision_note
    req.rejected_by = actor_id
    create_notification(
        session, soldier_id=req.requesting_soldier_id, type=NotificationType.swap_rejected,
        title="בקשת ההחלפה נדחתה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    live_candidates = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.status.in_(["pending", "accepted"]),
        )
    ).scalars().all()
    now = datetime.utcnow()
    for candidate in live_candidates:
        candidate.status = "cancelled"
        candidate.decided_at = now
        create_notification(
            session, soldier_id=candidate.soldier_id, type=NotificationType.swap_rejected,
            title="בקשת ההחלפה נדחתה", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
        )
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
    req = _lock_request(session, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_cancellable")
    before = {"status": req.status}
    req.status = "cancelled"
    live_candidates = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.status.in_(["pending", "accepted"]),
        )
    ).scalars().all()
    now = datetime.utcnow()
    for candidate in live_candidates:
        candidate.status = "cancelled"
        candidate.decided_at = now
        create_notification(
            session, soldier_id=candidate.soldier_id, type=NotificationType.swap_rejected,
            title="בקשת ההחלפה בוטלה ע\"י המבקש", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
        )
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
            SwapRequest.status == "open",
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
        status="open",
        requester_side_approved=False,
    )
    session.add(req)
    session.flush()
    candidate = SwapCandidate(
        swap_request_id=req.id, soldier_id=covering_soldier_id, source="marketplace",
        status="accepted", soldier_side_approved=True,
    )
    session.add(candidate)
    session.flush()

    create_notification(
        session,
        soldier_id=assignment.soldier_id,
        type=NotificationType.swap_offer,
        title="חייל אחר מבקש לקחת את התורנות שלך - נדרש אישורך",
        reference_type="swap_request",
        reference_id=req.id,
        actor_id=actor_id,
    )
    write_audit(
        session, actor_id=actor_id, action="swap.take_free",
        entity_type="swap_request", entity_id=req.id,
        after={
            "duty_assignment_id": str(assignment_id),
            "duty_date": req.duty_date.isoformat(),
            "covering_soldier_id": str(covering_soldier_id),
            "status": "open",
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
    """Covering soldier responds to an open swap request (from board or
    incoming), optionally attaching a counter-offer of their own assignments."""
    req = _lock_request(session, swap_id)
    if req is None:
        raise SwapError("swap_not_found")
    if req.status != "open":
        raise SwapError("swap_not_open")
    if req.requesting_soldier_id == covering_soldier_id:
        raise SwapError("cannot_cover_own_swap")
    eligible, reason = check_soldier_for_assignment(session, covering_soldier_id, req.duty_assignment_id)
    if not eligible:
        raise SwapError(f"cover_not_eligible:{reason}")
    _enforce_hierarchy_level_restriction(
        session, requesting_soldier_id=req.requesting_soldier_id, other_soldier_id=covering_soldier_id,
    )

    candidate = session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == swap_id,
            SwapCandidate.soldier_id == covering_soldier_id,
        )
    ).scalar_one_or_none()
    if candidate is None:
        if not req.open_to_marketplace:
            raise SwapError("not_targeted_at_you")
        candidate = SwapCandidate(swap_request_id=swap_id, soldier_id=covering_soldier_id, source="marketplace")
        session.add(candidate)
    elif candidate.status != "pending":
        raise SwapError("already_pending")

    candidate.offered_assignment_ids = [str(aid) for aid in offered_assignment_ids]
    candidate.status = "accepted"
    candidate.soldier_side_approved = True
    req.requester_side_approved = True

    create_notification(
        session, soldier_id=req.requesting_soldier_id, type=NotificationType.swap_offer,
        title="הגיעה הצעה לכיסוי הבקשה שלך", reference_type="swap_request", reference_id=req.id, actor_id=actor_id,
    )
    write_audit(
        session, actor_id=actor_id, action="swap.cover_offer", entity_type="swap_request",
        entity_id=req.id, after={"soldier_id": str(covering_soldier_id), "candidate_id": str(candidate.id)},
    )
    session.flush()
    _try_finalize(session, req, actor_id)
    session.flush()
    return req


def list_pending_approval(session: Session) -> list[SwapRequest]:
    request_ids = session.execute(
        select(SwapCandidate.swap_request_id).where(
            SwapCandidate.status.in_(["pending", "accepted"])
        ).distinct()
    ).scalars().all()
    if not request_ids:
        return []
    return list(
        session.execute(
            select(SwapRequest)
            .where(SwapRequest.status == "open", SwapRequest.id.in_(request_ids))
            .order_by(SwapRequest.duty_date.asc())
        )
        .scalars()
        .all()
    )


def expire_started_swaps(session: Session, *, today: date | None = None) -> int:
    """Cancel every open SwapRequest whose duty has already started (duty_date <= today)
    — once a duty is underway there's no one left to swap it with. Returns the count
    cancelled. Called periodically by the background worker (see app/swap_expiry_worker.py);
    there is no user actor for this system action, so notifications/audit use actor_id=None."""
    today = today or date.today()
    requests = session.execute(
        select(SwapRequest).where(SwapRequest.status == "open", SwapRequest.duty_date <= today)
    ).scalars().all()
    for req in requests:
        before = {"status": req.status}
        req.status = "cancelled"
        live_candidates = session.execute(
            select(SwapCandidate).where(
                SwapCandidate.swap_request_id == req.id,
                SwapCandidate.status.in_(["pending", "accepted"]),
            )
        ).scalars().all()
        now = datetime.utcnow()
        recipients = {req.requesting_soldier_id, *(c.soldier_id for c in live_candidates)}
        for candidate in live_candidates:
            candidate.status = "cancelled"
            candidate.decided_at = now
        for soldier_id in recipients:
            create_notification(
                session, soldier_id=soldier_id, type=NotificationType.swap_rejected,
                title="בקשת ההחלפה בוטלה — התורנות כבר התחילה", reference_type="swap_request",
                reference_id=req.id, actor_id=None,
            )
        write_audit(
            session, actor_id=None, action="swap.auto_expire", entity_type="swap_request",
            entity_id=req.id, before=before, after={"status": "cancelled"},
        )
    session.flush()
    return len(requests)
