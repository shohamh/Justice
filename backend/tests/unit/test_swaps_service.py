import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import DutyAssignment, SwapCandidate, SwapManagerApproval, SwapRequest
from app.services import swaps as svc
from app.services.approval_scope import commander_chain_for_soldier
from app.services.swaps import SwapError
from tests.helpers import create_node, create_soldier


def _published_assignment(session, *, soldier_id, node_id):
    from app.db.models import DutyType, DutyLocation
    dt = DutyType(name=f"dt_svc_{soldier_id}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_svc_{soldier_id}")
    session.add_all([dt, loc])
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=11),
        status="published",
    )
    session.add(a)
    session.flush()
    return a


def test_create_request_combining_targets_and_marketplace(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-1")
    requester = create_soldier(admin_session, personal_number="7710001", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7710002", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
        open_to_marketplace=True,
    )
    admin_session.flush()

    assert isinstance(req, SwapRequest)
    assert req.open_to_marketplace is True
    candidates = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()
    assert len(candidates) == 1
    assert candidates[0].soldier_id == target.id
    assert candidates[0].source == "invited"
    assert candidates[0].status == "pending"


def test_create_request_rejects_second_open_request_for_same_duty(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-2")
    requester = create_soldier(admin_session, personal_number="7710003", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="already_pending"):
        svc.create_request(
            admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
        )


def test_create_request_translates_integrity_error_from_stale_duplicate_guard(admin_session, monkeypatch):
    """Covers the TOCTOU gap the SELECT-based duplicate check can't close:
    two concurrent create_request calls for the same (requester, duty) can
    both pass the SELECT before either commits, so the real backstop is the
    partial unique index uq_swap_requests_one_open_per_requester_duty, which
    raises IntegrityError on whichever insert loses the race.

    We can't spin up real concurrent threads against the per-test session
    fixture, so instead we simulate the race directly: an open SwapRequest
    for (requester, duty) already exists, but we force create_request's own
    SELECT guard to (falsely, as it could under a real race) report "no
    existing open request". This proves the try/except around
    session.add(req); session.flush() in create_request correctly catches
    the resulting IntegrityError and translates it into the same
    SwapError("already_pending") the SELECT-based check raises normally,
    instead of letting a raw IntegrityError escape as an unhandled 500. It
    does not exercise real multi-threaded concurrency.
    """
    node = create_node(admin_session, level="unit", name="swap-svc-unit-race")
    requester = create_soldier(admin_session, personal_number="7710007", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    real_execute = admin_session.execute

    class _FakeNoneResult:
        def scalar_one_or_none(self):
            return None

    def _stale_guard_execute(statement, *args, **kwargs):
        # Only fake out the duplicate-open-request guard query inside
        # create_request (identifiable by referencing both the
        # swap_requests table and its status column); every other query
        # (e.g. the settings lookup for max targets) goes through untouched.
        sql = str(statement)
        if "swap_requests" in sql and "status" in sql:
            return _FakeNoneResult()
        return real_execute(statement, *args, **kwargs)

    monkeypatch.setattr(admin_session, "execute", _stale_guard_execute)

    with pytest.raises(SwapError, match="already_pending"):
        svc.create_request(
            admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
        )


def test_claim_request_creates_marketplace_candidate_without_cancelling_invited(admin_session):
    """claim_request itself no longer directly cancels other invited
    candidates as a side effect (unlike the old pre-unification behavior).
    In this test's setup the soldiers have no commander/duty-manager chain
    at all, so the claimant's claim (which sets both
    requester_side_approved and the claimant's own soldier_side_approved)
    is immediately fully-approved and _try_finalize legitimately wins the
    race for the claimant — cancelling the still-untouched invited
    candidate through the race mechanism, not through any direct
    claim_request side effect."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-3")
    requester = create_soldier(admin_session, personal_number="7710004", hierarchy_node_id=node.id)
    invited = create_soldier(admin_session, personal_number="7710005", hierarchy_node_id=node.id)
    claimant = create_soldier(admin_session, personal_number="7710006", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[invited.id], reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=claimant.id, actor_id=claimant.id)
    admin_session.flush()

    candidates = {c.soldier_id: c for c in admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()}
    assert len(candidates) == 2
    assert candidates[invited.id].status == "cancelled"  # cancelled by the finalize race, not by claim_request directly
    assert candidates[claimant.id].source == "marketplace"
    assert candidates[claimant.id].soldier_side_approved is True
    assert candidates[claimant.id].status == "applied"
    admin_session.refresh(req)
    assert req.status == "applied"


def test_approve_soldier_side_approves_only_the_callers_candidate(admin_session):
    """`a` and `b` are both invited candidates, so `a`'s own approval must
    only touch `a`'s candidate row — `b` stays untouched. Note this now
    finalizes the whole request: since `a` was specifically invited by the
    requester, `a`'s approval auto-implies the requester's consent too
    (see approve_soldier_side's "invited" source branch), and with no
    manager-approval chains configured for these test soldiers, that's
    enough to win the finalize race outright."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-4")
    requester = create_soldier(admin_session, personal_number="7710007", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710008", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710009", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.flush()
    admin_session.refresh(req)

    cands = {c.soldier_id: c for c in admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()}
    assert cands[a.id].soldier_side_approved is True
    assert cands[a.id].status == "applied"
    assert cands[b.id].soldier_side_approved is None
    assert cands[b.id].status == "cancelled"
    assert req.status == "applied"
    assert req.requester_side_approved is True


def test_approve_soldier_side_requester_shared_across_candidates(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-5")
    requester = create_soldier(admin_session, personal_number="7710010", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710011", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id)
    admin_session.flush()
    admin_session.refresh(req)
    assert req.requester_side_approved is True


def test_approve_soldier_side_rejects_for_a_non_party(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-6")
    requester = create_soldier(admin_session, personal_number="7710012", hierarchy_node_id=node.id)
    stranger = create_soldier(admin_session, personal_number="7710013", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="not_a_party"):
        svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=stranger.id, actor_id=stranger.id)


def test_approve_soldier_side_still_raises_when_request_was_rejected(admin_session):
    """The late-approval no-op only applies to the finalize-race-won
    ("applied") case. A request that was independently rejected (e.g. by a
    manager) before a stale/late requester-side approval call lands must
    still raise not_pending — the approval genuinely had no effect and the
    caller needs to know, unlike the applied case which is a harmless race
    outcome."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-6b")
    requester = create_soldier(admin_session, personal_number="7710013b", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710013c", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    # Set the status directly (rather than calling reject_request) to isolate
    # approve_soldier_side's behavior from the rejection path itself.
    req.status = "rejected"
    admin_session.flush()
    admin_session.refresh(req)
    assert req.status == "rejected"

    with pytest.raises(SwapError, match="not_pending"):
        svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id)


def test_finalize_first_fully_approved_candidate_wins_and_cancels_others(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-7")
    requester = create_soldier(admin_session, personal_number="7710014", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710015", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710016", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id)
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=b.id, actor_id=b.id)
    admin_session.flush()

    cand_a = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    # No commander/duty-manager chain in this test setup (soldiers have no
    # assigned commander), so _all_approved should already be true for both —
    # finalize picks whichever _try_finalize call reaches it first (a's,
    # since it ran first above).
    admin_session.refresh(req)
    assert req.status == "applied"
    cand_a2 = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    cand_b2 = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=b.id).one()
    assert cand_a2.status == "applied"
    assert cand_b2.status == "cancelled"


def test_declined_candidate_does_not_affect_other_candidates(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-8")
    requester = create_soldier(admin_session, personal_number="7710017", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710018", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710019", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.decline_candidate(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.flush()

    cand_a = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    cand_b = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=b.id).one()
    admin_session.refresh(req)
    assert cand_a.status == "declined"
    assert cand_b.status == "pending"
    assert req.status == "open"


def test_finalize_triggers_when_requester_approves_last(admin_session):
    """The requester's own consent can be the LAST missing piece for an
    already-fully-approved candidate — approve_soldier_side's requester
    branch must call _try_finalize too, not just the candidate branch.
    Regression test for a bug found during manual verification: the
    requester branch set requester_side_approved but never triggered the
    finalize race, leaving the request stuck open forever even though every
    other condition was already satisfied.

    Uses a marketplace-sourced candidate (inserted directly, bypassing
    claim_request/cover_offer) rather than an invited one: an invited
    candidate's own approval now auto-implies requester consent too (see
    approve_soldier_side's "invited" source branch), which would finalize
    the request right there and never exercise the requester branch's own
    _try_finalize call — the thing this test exists to check."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-requester-last")
    requester = create_soldier(admin_session, personal_number="7710030", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710031", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.add(SwapCandidate(swap_request_id=req.id, soldier_id=a.id, source="marketplace"))
    admin_session.flush()

    # Candidate approves first — requester_side_approved is still None (this
    # candidate is marketplace-sourced, not invited, so no auto-consent), so
    # this alone must NOT finalize yet.
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.flush()
    admin_session.refresh(req)
    assert req.status == "open"
    assert req.requester_side_approved is not True

    # Requester approves last — this is the final missing piece; finalize
    # must trigger from THIS call.
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id)
    admin_session.flush()
    admin_session.refresh(req)
    assert req.status == "applied"
    cand = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    assert cand.status == "applied"


def test_finalize_immediate_when_manager_approval_not_required(admin_session):
    """When swaps.require_manager_approval is off, both soldier-side
    confirmations alone finalize the request — no commander/duty-manager
    chain check should block it (regression check for the
    _candidate_fully_approved short-circuit)."""
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)

    node = create_node(admin_session, level="unit", name="swap-svc-unit-11")
    requester = create_soldier(admin_session, personal_number="7710025", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710026", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=a.id, actor_id=a.id)
    admin_session.flush()

    admin_session.refresh(req)
    assert req.status == "applied"


def test_cancel_request_cascades_to_all_live_candidates(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-9")
    requester = create_soldier(admin_session, personal_number="7710020", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710021", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710022", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    svc.cancel_request(admin_session, request_id=req.id, actor_id=requester.id)
    admin_session.flush()

    admin_session.refresh(req)
    assert req.status == "cancelled"
    for sid in (a.id, b.id):
        cand = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=sid).one()
        assert cand.status == "cancelled"


def test_take_free_creates_one_applied_candidate(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-10")
    owner = create_soldier(admin_session, personal_number="7710023", hierarchy_node_id=node.id)
    taker = create_soldier(admin_session, personal_number="7710024", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=owner.id, node_id=node.id)

    req, warnings = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=taker.id, actor_id=taker.id)
    admin_session.flush()

    # take_free now opens a normal swap request requiring the duty owner's
    # consent — it no longer applies the cover instantly.
    assert req.status == "open"
    assert req.requester_side_approved is False
    cand = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).one()
    assert cand.soldier_id == taker.id
    assert cand.source == "marketplace"
    assert cand.status == "accepted"
    assert cand.soldier_side_approved is True

    # node has no commander, so once the owner approves, the swap finalizes
    # with no manager-approval gate.
    finalized = svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=owner.id, actor_id=owner.id)
    admin_session.flush()
    assert finalized.status == "applied"
    admin_session.refresh(cand)
    assert cand.status == "applied"


def test_reject_manager_row_raises_for_unauthorized_actor(admin_session):
    """reject_manager_row must raise (not silently no-op) when the actor
    doesn't qualify as a required approver for any (side, kind) on this
    request. Regression test: this used to return the untouched SwapRequest
    with no error at all, hiding from the caller/UI that nothing happened."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-reject-mgr-unauth")
    requester = create_soldier(admin_session, personal_number="7710040", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710041", hierarchy_node_id=node.id)
    stranger = create_soldier(admin_session, personal_number="7710042")  # no hierarchy node, no chain at all
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="not_required_approver"):
        svc.reject_manager_row(admin_session, request_id=req.id, actor_id=stranger.id, candidate_id=None)

    admin_session.refresh(req)
    assert req.status == "open"


def test_reject_manager_row_raises_candidate_mismatch(admin_session):
    """reject_manager_row must validate that candidate_id actually belongs
    to request_id — a mismatched pair (candidate from a different swap
    request) is a caller bug and must raise, not silently act on/ignore the
    wrong request's candidate."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-candidate-mismatch")
    requester = create_soldier(admin_session, personal_number="7710043", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710044", hierarchy_node_id=node.id)
    other_requester = create_soldier(admin_session, personal_number="7710045", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710046", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    other_assignment = _published_assignment(admin_session, soldier_id=other_requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id], reason=None, open_to_marketplace=False,
    )
    other_req = svc.create_request(
        admin_session, requesting_soldier_id=other_requester.id, duty_assignment_id=other_assignment.id,
        target_soldier_id=None, target_soldier_ids=[b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()
    other_candidate = admin_session.query(SwapCandidate).filter_by(swap_request_id=other_req.id, soldier_id=b.id).one()

    # other_candidate genuinely belongs to other_req, not req — passing it
    # in alongside req.id must raise rather than silently proceed.
    with pytest.raises(SwapError, match="candidate_mismatch"):
        svc.reject_manager_row(admin_session, request_id=req.id, actor_id=requester.id, candidate_id=other_candidate.id)

    with pytest.raises(SwapError, match="candidate_mismatch"):
        svc.is_chain_commander_for_side(
            admin_session, request_id=req.id, side="covering", commander_id=requester.id, candidate_id=other_candidate.id,
        )

    with pytest.raises(SwapError, match="candidate_mismatch"):
        svc.approve_manager_side_override(
            admin_session, request_id=req.id, side="covering", actor_id=requester.id, candidate_id=other_candidate.id,
        )


def test_approve_soldier_side_auto_sets_requester_consent_only_for_invited_candidates(admin_session):
    """Fix #4 consistency check: an invited candidate's own approval implies
    requester consent (the requester specifically chose them), but a
    marketplace-claimed candidate's approval must NOT — the requester never
    chose a marketplace claimant, so their separate approval is still
    required. This directly exercises approve_soldier_side's candidate
    branch for both `source` values."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-source-branch")
    requester = create_soldier(admin_session, personal_number="7710047", hierarchy_node_id=node.id)
    invited = create_soldier(admin_session, personal_number="7710048", hierarchy_node_id=node.id)
    marketplace_claimant = create_soldier(admin_session, personal_number="7710049", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[invited.id], reason=None, open_to_marketplace=True,
    )
    # Directly insert a pending marketplace-sourced candidate (bypassing
    # claim_request/cover_offer, which both already auto-set
    # requester_side_approved at creation time regardless of source) so we
    # can isolate approve_soldier_side's own source-based branching.
    admin_session.add(SwapCandidate(swap_request_id=req.id, soldier_id=marketplace_claimant.id, source="marketplace"))
    admin_session.flush()

    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=marketplace_claimant.id, actor_id=marketplace_claimant.id)
    admin_session.flush()
    admin_session.refresh(req)
    assert req.requester_side_approved is not True

    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=invited.id, actor_id=invited.id)
    admin_session.flush()
    admin_session.refresh(req)
    assert req.requester_side_approved is True


def test_reject_manager_row_per_candidate_does_not_escalate_to_whole_request(admin_session):
    """A manager who qualifies on BOTH sides (same node commands the requester
    and the candidates) rejecting ONE candidate must cancel only that
    candidate. Previously the requester-side qualification leaked through and
    escalated to reject_request, killing the parent and every sibling."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-reject-scoped")
    cmd = create_soldier(admin_session, personal_number="7710050", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    requester = create_soldier(admin_session, personal_number="7710051", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710052", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="7710053", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()
    cand_a = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    cand_b = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=b.id).one()

    # cmd is in the requester's chain AND in both candidates' chains.
    assert cmd.id in commander_chain_for_soldier(admin_session, requester.id)
    assert cmd.id in commander_chain_for_soldier(admin_session, a.id)

    svc.reject_manager_row(admin_session, request_id=req.id, actor_id=cmd.id, candidate_id=cand_a.id)
    admin_session.flush()

    admin_session.refresh(req)
    admin_session.refresh(cand_a)
    admin_session.refresh(cand_b)
    assert req.status == "open"
    assert cand_a.status == "cancelled"
    assert cand_b.status == "pending"

    rows = admin_session.query(SwapManagerApproval).filter_by(swap_request_id=req.id).all()
    assert [r.side for r in rows] == ["covering"]
    assert rows[0].swap_candidate_id == cand_a.id


def test_reject_manager_row_allows_override_authorized_actor(admin_session):
    """An actor with no qualifying chain row at all (an admin, or a
    broader-scope commander) may still reject when the caller signals it has
    already authorized them — mirroring approve_manager_side's override path.
    Without that signal the strict `not_required_approver` behaviour stands
    (see test_reject_manager_row_raises_for_unauthorized_actor)."""
    node = create_node(admin_session, level="unit", name="swap-svc-unit-reject-override")
    requester = create_soldier(admin_session, personal_number="7710060", hierarchy_node_id=node.id)
    a = create_soldier(admin_session, personal_number="7710061", hierarchy_node_id=node.id)
    admin = create_soldier(admin_session, personal_number="7710062", role="admin")  # no node, no chain
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()
    cand_a = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()

    # Strict path first: no override -> still raises, both scopes.
    with pytest.raises(SwapError, match="not_required_approver"):
        svc.reject_manager_row(admin_session, request_id=req.id, actor_id=admin.id, candidate_id=None)
    with pytest.raises(SwapError, match="not_required_approver"):
        svc.reject_manager_row(admin_session, request_id=req.id, actor_id=admin.id, candidate_id=cand_a.id)

    # Per-candidate reject via the override path: scoped to that candidate.
    svc.reject_manager_row(
        admin_session, request_id=req.id, actor_id=admin.id, candidate_id=cand_a.id,
        is_authorized_override=True,
    )
    admin_session.flush()
    admin_session.refresh(req)
    admin_session.refresh(cand_a)
    assert req.status == "open"
    assert cand_a.status == "cancelled"
    # No chain row is invented for an actor who holds none.
    assert admin_session.query(SwapManagerApproval).filter_by(swap_request_id=req.id).count() == 0

    # Whole-request reject via the override path (callable form, as the route
    # passes it) kills the request.
    svc.reject_manager_row(
        admin_session, request_id=req.id, actor_id=admin.id, candidate_id=None,
        decision_note="nope", is_authorized_override=lambda: True,
    )
    admin_session.flush()
    admin_session.refresh(req)
    assert req.status == "rejected"
    assert req.decision_note == "nope"


def test_concurrent_finalize_of_two_candidates_applies_only_one(admin_session, admin_engine):
    """Two candidates each one manager approval short, cleared by two different
    commanders in two genuinely concurrent transactions.

    Without the SELECT ... FOR UPDATE on the parent SwapRequest at the top of
    _try_finalize, both transactions read status='open', both pick a winner and
    both run _apply_cover — and duty_day_overrides has no unique constraint on
    (duty_assignment_id, date), so that lands two conflicting override rows for
    the same day plus a duplicate 'swap completed' notification pair. With the
    lock, the loser blocks until the winner commits, re-reads status='applied'
    and no-ops.
    """
    import threading

    from sqlalchemy.orm import sessionmaker

    from app.db.models import DutyDayOverride

    req_node = create_node(admin_session, level="unit", name="swap-svc-race-req")
    a_node = create_node(admin_session, level="unit", name="swap-svc-race-a")
    b_node = create_node(admin_session, level="unit", name="swap-svc-race-b")
    req_cmd = create_soldier(admin_session, personal_number="7710070", role="commander")
    a_cmd = create_soldier(admin_session, personal_number="7710071", role="commander")
    b_cmd = create_soldier(admin_session, personal_number="7710072", role="commander")
    req_node.commander_id = req_cmd.id
    a_node.commander_id = a_cmd.id
    b_node.commander_id = b_cmd.id
    admin_session.commit()

    requester = create_soldier(admin_session, personal_number="7710073", hierarchy_node_id=req_node.id)
    a = create_soldier(admin_session, personal_number="7710074", hierarchy_node_id=a_node.id)
    b = create_soldier(admin_session, personal_number="7710075", hierarchy_node_id=b_node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=req_node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[a.id, b.id], reason=None, open_to_marketplace=False,
    )
    admin_session.flush()
    cand_a = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=a.id).one()
    cand_b = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id, soldier_id=b.id).one()

    # Drive both candidates to "one approval short": both soldiers accepted,
    # requester side (soldier + its chain commander) fully cleared. No duty
    # managers exist, so duty_manager_chain_for_soldier is empty on every side
    # and only the commander kind is required.
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=b.id, actor_id=b.id)
    svc.approve_manager_row(admin_session, request_id=req.id, actor_id=req_cmd.id, candidate_id=cand_a.id)
    admin_session.commit()
    assert admin_session.get(SwapRequest, req.id).status == "open"

    request_id, cand_a_id, cand_b_id = req.id, cand_a.id, cand_b.id
    assignment_id = assignment.id
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def approve(actor_id, candidate_id):
        try:
            with SessionLocal() as s:
                # Warm the connection/transaction before the barrier so the two
                # threads hit _try_finalize as close together as possible.
                assert s.get(SwapRequest, request_id) is not None
                barrier.wait(timeout=30)
                svc.approve_manager_row(s, request_id=request_id, actor_id=actor_id, candidate_id=candidate_id)
                s.commit()
        except BaseException as exc:  # noqa: BLE001 - re-raised via `errors` below
            errors.append(exc)

    threads = [
        threading.Thread(target=approve, args=(a_cmd.id, cand_a_id)),
        threading.Thread(target=approve, args=(b_cmd.id, cand_b_id)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "a finalize thread deadlocked / never returned"
    # The loser blocks on the lock until the winner commits, then re-reads the
    # request under the lock and finds status='applied'. approve_manager_row's
    # pre-existing "not_pending" guard then rejects the late approval — that is
    # the correct outcome (nothing is applied twice), so it's the ONLY error
    # tolerated here. In particular a DeadlockDetected would mean the exclusive
    # lock is being taken after a child insert already holds FOR KEY SHARE on
    # the same row, i.e. acquired too late to be safe.
    assert all(isinstance(e, SwapError) and str(e) == "not_pending" for e in errors), (
        f"racing approvals raised something other than the late-arrival guard: {errors!r}"
    )
    assert len(errors) <= 1, f"both approvals failed, nothing finalized: {errors!r}"

    admin_session.expire_all()
    finalized = admin_session.get(SwapRequest, request_id)
    assert finalized.status == "applied"

    statuses = sorted(
        c.status
        for c in admin_session.query(SwapCandidate).filter_by(swap_request_id=request_id).all()
    )
    assert statuses == ["applied", "cancelled"], f"exactly one candidate must win, got {statuses}"

    overrides = admin_session.query(DutyDayOverride).filter_by(duty_assignment_id=assignment_id).all()
    assert len(overrides) == 1, f"double-finalize wrote {len(overrides)} day overrides"
    winner_id = (
        admin_session.query(SwapCandidate)
        .filter_by(swap_request_id=request_id, status="applied").one().soldier_id
    )
    assert overrides[0].effective_soldier_id == winner_id


def test_add_targets_happy_path(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-1")
    requester = create_soldier(admin_session, personal_number="7720001", hierarchy_node_id=node.id)
    target1 = create_soldier(admin_session, personal_number="7720002", hierarchy_node_id=node.id)
    target2 = create_soldier(admin_session, personal_number="7720003", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target1.id], reason=None,
    )
    admin_session.flush()

    result = svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target2.id])
    admin_session.flush()

    assert result.id == req.id
    candidates = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()
    assert {c.soldier_id for c in candidates} == {target1.id, target2.id}
    added = next(c for c in candidates if c.soldier_id == target2.id)
    assert added.source == "invited"
    assert added.status == "pending"


def test_add_targets_rejects_already_invited_soldier(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-2")
    requester = create_soldier(admin_session, personal_number="7720004", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720005", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match=f"already_invited:{target.id}"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target.id])


def test_add_targets_rejects_already_invited_soldier_regardless_of_status(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-status")
    requester = create_soldier(admin_session, personal_number="7720008", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720009", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
    )
    admin_session.flush()

    candidate = admin_session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == req.id, SwapCandidate.soldier_id == target.id,
        )
    ).scalar_one()
    candidate.status = "declined"
    admin_session.flush()

    with pytest.raises(SwapError, match=f"already_invited:{target.id}"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target.id])


def test_add_targets_rejects_duplicate_within_same_call(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-dup")
    requester = create_soldier(admin_session, personal_number="7720006", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720007", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match=f"already_invited:{target.id}"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target.id, target.id])


def test_add_targets_counts_existing_candidates_against_cap(admin_session):
    from app.services.settings_loader import set_setting

    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-cap")
    requester = create_soldier(admin_session, personal_number="7720008", hierarchy_node_id=node.id)
    t1 = create_soldier(admin_session, personal_number="7720009", hierarchy_node_id=node.id)
    t2 = create_soldier(admin_session, personal_number="7720010", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)
    set_setting(admin_session, "swaps.max_specific_targets", "1", actor_id=None)
    admin_session.flush()

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[t1.id], reason=None,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="target_limit_reached"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[t2.id])


def test_add_targets_rejects_when_request_not_open(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-addtargets-notopen")
    requester = create_soldier(admin_session, personal_number="7720011", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720012", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.cancel_request(admin_session, request_id=req.id)
    admin_session.flush()

    with pytest.raises(SwapError, match="not_open"):
        svc.add_targets(admin_session, request_id=req.id, target_soldier_ids=[target.id])


def test_publish_to_marketplace_happy_path(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-publish-1")
    requester = create_soldier(admin_session, personal_number="7720013", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720014", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
    )
    admin_session.flush()
    assert req.open_to_marketplace is False

    result = svc.publish_to_marketplace(admin_session, request_id=req.id)
    admin_session.flush()

    assert result.open_to_marketplace is True


def test_publish_to_marketplace_rejects_when_already_published(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-publish-2")
    requester = create_soldier(admin_session, personal_number="7720015", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="already_on_marketplace"):
        svc.publish_to_marketplace(admin_session, request_id=req.id)


def test_publish_to_marketplace_rejects_when_request_not_open(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-publish-3")
    requester = create_soldier(admin_session, personal_number="7720016", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7720017", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
    )
    admin_session.flush()
    svc.cancel_request(admin_session, request_id=req.id)
    admin_session.flush()

    with pytest.raises(SwapError, match="not_open"):
        svc.publish_to_marketplace(admin_session, request_id=req.id)
