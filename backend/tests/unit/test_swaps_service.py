import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import DutyAssignment, SwapCandidate, SwapRequest
from app.services import swaps as svc
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

    cands = {c.soldier_id: c for c in admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()}
    assert cands[a.id].soldier_side_approved is True
    assert cands[a.id].status == "accepted"
    assert cands[b.id].soldier_side_approved is None
    assert cands[b.id].status == "pending"


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
