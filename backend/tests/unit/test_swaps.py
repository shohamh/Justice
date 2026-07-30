from datetime import date
from decimal import Decimal

from app.db.models import DutyAssignment, DutyDayOverride, DutyLocation, DutyType, Notification, NotificationType, PersonalConstraint, Soldier, SwapCandidate, SwapRequest, SystemSetting
from sqlalchemy import select
from app.services import swaps as svc
from app.services.settings_loader import set_setting
from tests.helpers import create_node, create_soldier


def _seed(session):
    dt = DutyType(name="שמירה-swap", score_per_day=1)
    loc = DutyLocation(name="עמדה-swap")
    a = Soldier(personal_number="swapA", full_name="A", password_hash="x", role="soldier",
                enrolled_at=date(2026, 1, 1), must_change_password=False)
    b = Soldier(personal_number="swapB", full_name="B", password_hash="x", role="soldier",
                enrolled_at=date(2026, 1, 1), must_change_password=False)
    session.add_all([dt, loc, a, b])
    session.flush()
    assignment = DutyAssignment(
        soldier_id=a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 11), status="published",
    )
    session.add(assignment)
    session.flush()
    return a, b, assignment


def _candidate(session, request_id, soldier_id) -> SwapCandidate | None:
    """Fetch the SwapCandidate for (request_id, soldier_id) — the unified
    schema's replacement for a single covering_soldier_id/target_soldier_id
    column directly on SwapRequest."""
    return session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == request_id,
            SwapCandidate.soldier_id == soldier_id,
        )
    ).scalar_one_or_none()


def test_create_open_request(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="busy", actor_id=a.id, open_to_marketplace=True,
    )
    assert req.status == "open"
    assert req.open_to_marketplace is True
    assert _candidate(admin_session, req.id, b.id) is None


def test_create_direct_request(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=b.id, reason="cover me", actor_id=a.id,
    )
    assert req.status == "open"
    candidate = _candidate(admin_session, req.id, b.id)
    assert candidate is not None
    assert candidate.source == "invited"


def test_cannot_request_others_duty(admin_session):
    a, b, assignment = _seed(admin_session)
    try:
        svc.create_request(
            admin_session, requesting_soldier_id=b.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, reason="x", actor_id=b.id, open_to_marketplace=True,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "not_your_duty"


def test_claim_auto_applies_when_approval_off(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    out = svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    assert out.status == "applied"
    candidate = _candidate(admin_session, req.id, b.id)
    assert candidate is not None and candidate.status == "applied"
    ov = admin_session.get(DutyDayOverride, out.resulting_override_id)
    assert ov is not None
    assert ov.effective_soldier_id == b.id
    assert ov.reason == "replacement"


def test_claim_queues_when_approval_on(admin_session):
    # NOTE: with no commander/duty-manager chain at all for either soldier
    # (plain _seed soldiers have no hierarchy_node_id), _candidate_fully_approved
    # treats the manager-approval requirement as vacuously satisfied the
    # moment both soldier-side flags are set by claim_request — see
    # test_swap_applies_only_after_manager_approval (which uses
    # _seed_with_commander) for the case where a real commander chain
    # actually gates finalization. This test now documents that a bare
    # require_manager_approval=True setting alone, without any commander in
    # scope, still finalizes immediately.
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    out = svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    assert out.status == "applied"
    assert out.resulting_override_id is not None


def _seed_with_commander(session):
    """Like _seed, but places both soldiers under a hierarchy node with a
    commander in scope, so manager approval is actually required (and
    actually gate-able) for this swap — unlike the plain _seed helper, whose
    soldiers have no hierarchy_node_id and therefore no commander chain at
    all, so _all_approved would consider manager approval vacuously
    satisfied the moment both soldier-side flags are auto-set."""
    dt = DutyType(name="dt_mgr_swap", score_per_day=1)
    loc = DutyLocation(name="loc_mgr_swap")
    session.add_all([dt, loc])
    session.flush()

    commander = create_soldier(session, personal_number="mgr_cmd", role="commander")
    node = create_node(session, level="unit", name="unit_mgr_swap", commander_id=commander.id)
    a = create_soldier(session, personal_number="mgr_a", hierarchy_node_id=node.id)
    b = create_soldier(session, personal_number="mgr_b", hierarchy_node_id=node.id)

    assignment = DutyAssignment(
        soldier_id=a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 11), status="published",
    )
    session.add(assignment)
    session.flush()
    return commander, a, b, assignment


def test_swap_applies_only_after_manager_approval(admin_session):
    # Soldier-side approval is auto-set the moment a swap is claimed (asking
    # for / claiming a swap already implies consent — see claim_request), so
    # this test's job is no longer to prove a two-step *soldier* approval
    # gate. It's to prove the swap still doesn't finalize on claim alone when
    # a commander is in scope, and DOES finalize once that commander approves.
    commander, a, b, assignment = _seed_with_commander(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()

    # Both soldier-side flags are already auto-approved at this point, but the
    # commander (in scope for both sides) hasn't signed off yet.
    reloaded = admin_session.get(SwapRequest, req.id)
    candidate = _candidate(admin_session, req.id, b.id)
    assert reloaded.status == "open"
    assert reloaded.requester_side_approved is True
    assert candidate is not None and candidate.soldier_side_approved is True

    # candidate_id=candidate.id: the commander is the shared chain for both
    # requester and covering sides here (same node), and — unlike the old
    # single-candidate-per-SwapRequest schema — a manager-approval row for
    # the covering side must now be scoped to a specific candidate.
    out = svc.approve_manager_row(admin_session, request_id=req.id, actor_id=commander.id, candidate_id=candidate.id)
    assert out.status == "applied"
    assert out.resulting_override_id is not None


def test_reject_sets_status_and_no_override(admin_session):
    # Uses _seed_with_commander (not the plain _seed) so a real commander
    # chain gates finalization — with no commander in scope at all, claiming
    # an open-to-marketplace request now finalizes immediately (see
    # test_claim_queues_when_approval_on), leaving nothing left to reject.
    commander, a, b, assignment = _seed_with_commander(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()
    out = svc.reject_request(admin_session, request_id=req.id, decision_note="no", actor_id=None)
    assert out.status == "rejected"
    assert out.resulting_override_id is None


def test_cancel_open_request(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.cancel_request(admin_session, request_id=req.id, actor_id=a.id)
    assert admin_session.get(SwapRequest, req.id).status == "cancelled"


def test_claim_request_no_approval_notifies_both_sides(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()
    for sid in (a.id, b.id):
        notif = admin_session.query(Notification).filter_by(
            soldier_id=sid, type=NotificationType.swap_accepted,
        ).one_or_none()
        assert notif is not None


def test_cover_offer_no_approval_notifies_both_sides(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.cover_offer(admin_session, swap_id=req.id, covering_soldier_id=b.id,
                    offered_assignment_ids=[], actor_id=b.id)
    admin_session.flush()
    for sid in (a.id, b.id):
        notif = admin_session.query(Notification).filter_by(
            soldier_id=sid, type=NotificationType.swap_accepted,
        ).one_or_none()
        assert notif is not None


def test_reject_request_notifies_covering_soldier(admin_session):
    # See test_reject_sets_status_and_no_override — needs a real commander
    # chain so the request is still "open" (rejectable) when reject_request
    # is called, rather than already auto-finalized to "applied" by claim.
    commander, a, b, assignment = _seed_with_commander(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()
    svc.reject_request(admin_session, request_id=req.id, decision_note="no", actor_id=None)
    admin_session.flush()
    notif = admin_session.query(Notification).filter_by(
        soldier_id=b.id, type=NotificationType.swap_rejected,
    ).one_or_none()
    assert notif is not None


def test_cancel_request_notifies_covering_soldier(admin_session):
    # See test_reject_sets_status_and_no_override for why a commander chain
    # is needed here too (otherwise claim already finalizes the request).
    commander, a, b, assignment = _seed_with_commander(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()
    svc.cancel_request(admin_session, request_id=req.id, actor_id=a.id)
    admin_session.flush()
    notif = admin_session.query(Notification).filter_by(
        soldier_id=b.id, type=NotificationType.swap_rejected,
    ).one_or_none()
    assert notif is not None


def test_expire_started_swaps_cancels_request_whose_duty_already_started(admin_session):
    commander, a, b, assignment = _seed_with_commander(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()

    # assignment.start_date is 2026-06-10 (see _seed) — "today" past that means the duty started.
    count = svc.expire_started_swaps(admin_session, today=date(2026, 6, 10))
    admin_session.flush()

    assert count == 1
    assert admin_session.get(SwapRequest, req.id).status == "cancelled"
    candidate = _candidate(admin_session, req.id, b.id)
    assert candidate.status == "cancelled"
    for sid in (a.id, b.id):
        notif = admin_session.query(Notification).filter_by(
            soldier_id=sid, type=NotificationType.swap_rejected,
        ).one_or_none()
        assert notif is not None


def test_expire_started_swaps_leaves_future_duty_requests_open(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()

    # "today" before assignment.start_date (2026-06-10) — duty hasn't started yet.
    count = svc.expire_started_swaps(admin_session, today=date(2026, 6, 1))
    admin_session.flush()

    assert count == 0
    assert admin_session.get(SwapRequest, req.id).status == "open"


def test_expire_started_swaps_ignores_already_cancelled_requests(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    svc.cancel_request(admin_session, request_id=req.id, actor_id=a.id)
    admin_session.flush()

    count = svc.expire_started_swaps(admin_session, today=date(2026, 6, 10))
    assert count == 0


def _reserve_assignment(session, soldier_id, dt_id, loc_id, start, end, status="published"):
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt_id, duty_location_id=loc_id,
        start_date=start, end_date=end, status=status, is_reserve=True,
    )
    session.add(a)
    session.flush()
    return a


def _seed_with_reserve(session):
    dt = DutyType(name="שמירה-res-swap", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-res-swap")
    owner = Soldier(personal_number="rswap-owner", full_name="Owner", password_hash="x",
                    role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    taker = Soldier(personal_number="rswap-taker", full_name="Taker", password_hash="x",
                    role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    session.add_all([dt, loc, owner, taker])
    session.flush()
    reserve_a = DutyAssignment(
        soldier_id=owner.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 8),
        status="published", is_reserve=True,
    )
    session.add(reserve_a)
    session.flush()
    return owner, taker, reserve_a, dt, loc


def test_take_free_reserve_blocked_when_feature_disabled(admin_session):
    owner, taker, reserve_a, _, _ = _seed_with_reserve(admin_session)
    admin_session.add(SystemSetting(key="reserves.allow_take_free", value=False))
    admin_session.flush()
    try:
        svc.take_free(admin_session, assignment_id=reserve_a.id, covering_soldier_id=taker.id, actor_id=taker.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "reserve_take_free_disabled"


def test_take_free_reserve_blocked_when_cap_exceeded(admin_session):
    owner, taker, reserve_a, dt, loc = _seed_with_reserve(admin_session)
    # Give taker 14 existing reserve days in the same window (Aug 1-30)
    _reserve_assignment(admin_session, taker.id, dt.id, loc.id, date(2026, 8, 10), date(2026, 8, 24))
    try:
        svc.take_free(admin_session, assignment_id=reserve_a.id, covering_soldier_id=taker.id, actor_id=taker.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "reserve_cap_exceeded:21/14/30"


def test_take_free_reserve_succeeds_under_cap(admin_session):
    owner, taker, reserve_a, _, _ = _seed_with_reserve(admin_session)
    # No existing reserves for taker → under cap
    result, warnings = svc.take_free(admin_session, assignment_id=reserve_a.id, covering_soldier_id=taker.id, actor_id=taker.id)
    assert result.status in ("open", "applied")
    assert warnings == []


def test_take_free_primary_unaffected_by_reserve_setting(admin_session):
    # Disabling allow_take_free must NOT block take-free on primary assignments
    a, b, assignment = _seed(admin_session)  # _seed creates a primary assignment
    admin_session.add(SystemSetting(key="reserves.allow_take_free", value=False))
    admin_session.flush()
    # Should succeed — primary assignment, not reserve
    result = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    assert result is not None


def _approved_constraint(session, soldier_id, start, end):
    c = PersonalConstraint(
        soldier_id=soldier_id, start_date=start, end_date=end,
        reason="busy", status="approved",
    )
    session.add(c)
    session.flush()
    return c


def test_claim_blocked_when_covering_has_constraint(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    _approved_constraint(admin_session, b.id, assignment.start_date, assignment.end_date)
    try:
        svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")


def test_claim_blocked_when_covering_has_conflict_assignment(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    conflict = DutyAssignment(
        soldier_id=b.id,
        duty_type_id=assignment.duty_type_id,
        duty_location_id=assignment.duty_location_id,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        status="published",
    )
    admin_session.add(conflict)
    admin_session.flush()
    try:
        svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")


def test_cover_offer_blocked_when_covering_has_constraint(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id, open_to_marketplace=True,
    )
    admin_session.flush()
    _approved_constraint(admin_session, b.id, assignment.start_date, assignment.end_date)
    try:
        svc.cover_offer(admin_session, swap_id=req.id, covering_soldier_id=b.id,
                        offered_assignment_ids=[], actor_id=b.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")


def test_take_free_blocked_when_covering_has_constraint(admin_session):
    a, b, assignment = _seed(admin_session)
    _approved_constraint(admin_session, b.id, assignment.start_date, assignment.end_date)
    try:
        svc.take_free(admin_session, assignment_id=assignment.id,
                      covering_soldier_id=b.id, actor_id=b.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")


def test_create_direct_request_blocked_when_target_has_constraint(admin_session):
    a, b, assignment = _seed(admin_session)
    _approved_constraint(admin_session, b.id, assignment.start_date, assignment.end_date)
    try:
        svc.create_request(
            admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
            target_soldier_id=b.id, reason="cover me", actor_id=a.id,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc).startswith("cover_not_eligible:")


def _seed_cross_branch(session):
    dt = DutyType(name="שמירה-hier-swap", score_per_day=1)
    loc = DutyLocation(name="עמדה-hier-swap")
    session.add_all([dt, loc])
    session.flush()

    branch_a = create_node(session, level="branch", name="branch_a")
    branch_b = create_node(session, level="branch", name="branch_b")
    unit_a = create_node(session, level="unit", name="unit_a", parent=branch_a)
    unit_b = create_node(session, level="unit", name="unit_b", parent=branch_b)
    requester = create_soldier(session, personal_number="7970001", hierarchy_node_id=unit_a.id)
    target = create_soldier(session, personal_number="7970002", hierarchy_node_id=unit_b.id)

    assignment = DutyAssignment(
        soldier_id=requester.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 11), status="published",
    )
    session.add(assignment)
    session.flush()
    return requester, target, assignment


def test_create_request_blocked_across_hierarchy_level_when_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    set_setting(admin_session, "swaps.restrict_to_hierarchy_level", "branch", actor_id=None)
    admin_session.flush()

    try:
        svc.create_request(
            admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
            target_soldier_id=target.id, reason=None, actor_id=requester.id,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "hierarchy_level_mismatch"


def test_create_request_allowed_across_hierarchy_level_when_not_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=target.id, reason=None, actor_id=requester.id,
    )
    assert req.status == "open"


def test_claim_open_board_blocked_across_hierarchy_level_when_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason=None, actor_id=requester.id, open_to_marketplace=True,
    )
    admin_session.flush()
    set_setting(admin_session, "swaps.restrict_to_hierarchy_level", "branch", actor_id=None)
    admin_session.flush()

    try:
        svc.claim_request(
            admin_session, request_id=req.id, covering_soldier_id=target.id, actor_id=target.id,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "hierarchy_level_mismatch"


def test_claim_open_board_allowed_across_hierarchy_level_when_not_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason=None, actor_id=requester.id, open_to_marketplace=True,
    )
    admin_session.flush()
    out = svc.claim_request(
        admin_session, request_id=req.id, covering_soldier_id=target.id, actor_id=target.id,
    )
    assert out.status in ("open", "applied")


def test_cover_offer_blocked_across_hierarchy_level_when_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason=None, actor_id=requester.id, open_to_marketplace=True,
    )
    admin_session.flush()
    set_setting(admin_session, "swaps.restrict_to_hierarchy_level", "branch", actor_id=None)
    admin_session.flush()

    try:
        svc.cover_offer(
            admin_session, swap_id=req.id, covering_soldier_id=target.id,
            offered_assignment_ids=[], actor_id=target.id,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "hierarchy_level_mismatch"


def test_cover_offer_allowed_across_hierarchy_level_when_not_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason=None, actor_id=requester.id, open_to_marketplace=True,
    )
    admin_session.flush()
    out = svc.cover_offer(
        admin_session, swap_id=req.id, covering_soldier_id=target.id,
        offered_assignment_ids=[], actor_id=target.id,
    )
    assert out.status in ("open", "applied")


def test_take_free_blocked_across_hierarchy_level_when_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    set_setting(admin_session, "swaps.restrict_to_hierarchy_level", "branch", actor_id=None)
    admin_session.flush()

    try:
        svc.take_free(
            admin_session, assignment_id=assignment.id,
            covering_soldier_id=target.id, actor_id=target.id,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "hierarchy_level_mismatch"


def test_take_free_allowed_across_hierarchy_level_when_not_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    req, warnings = svc.take_free(
        admin_session, assignment_id=assignment.id,
        covering_soldier_id=target.id, actor_id=target.id,
    )
    assert req.status == "open"
    assert req.requester_side_approved is False
    # requester and target have no commander/duty-manager chain in this fixture,
    # so once the duty owner approves, the swap finalizes with no manager gate.
    finalized = svc.approve_soldier_side(
        admin_session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id,
    )
    assert finalized.status == "applied"


def test_take_free_does_not_apply_cover_without_owner_approval(admin_session):
    a, b, assignment = _seed(admin_session)
    req, warnings = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.commit()
    assert req.status == "open"
    fresh = admin_session.get(DutyAssignment, assignment.id)
    assert fresh.soldier_id == a.id  # duty still belongs to the original owner


def test_take_free_finalizes_only_after_owner_approves(admin_session):
    a, b, assignment = _seed(admin_session)
    req, warnings = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()
    finalized = svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.commit()
    assert finalized.status == "applied"


def test_take_free_blocked_by_manager_approval_gate_when_owner_has_commander(admin_session):
    """When require_manager_approval is on and the duty owner has a commander,
    owner approval alone must not finalize the swap."""
    node = create_node(admin_session, level="unit", name="tf_manager_gate")
    cmd = create_soldier(admin_session, personal_number="tf_cmd_1", role="commander")
    node.commander_id = cmd.id
    admin_session.flush()
    a = create_soldier(admin_session, personal_number="tf_owner_1", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="tf_taker_1")
    dt = DutyType(name="dt_tf_gate", score_per_day=1)
    loc = DutyLocation(name="loc_tf_gate")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 11), status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()

    req, warnings = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()
    after_owner_approval = svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.commit()
    assert after_owner_approval.status == "open"  # still waiting on the commander's SwapManagerApproval


def _seed_multi_target(session, n=3):
    dt = DutyType(name="dt_multi_target", score_per_day=1)
    loc = DutyLocation(name="loc_multi_target")
    requester = Soldier(personal_number="mt_req", full_name="Req", password_hash="x", role="soldier",
                        enrolled_at=date(2026, 1, 1), must_change_password=False)
    targets = [
        Soldier(personal_number=f"mt_s{i}", full_name=f"S{i}", password_hash="x", role="soldier",
                enrolled_at=date(2026, 1, 1), must_change_password=False)
        for i in range(1, n + 1)
    ]
    session.add_all([dt, loc, requester, *targets])
    session.flush()
    assignment = DutyAssignment(
        soldier_id=requester.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 11), status="published",
    )
    session.add(assignment)
    session.flush()
    return requester, targets, assignment


def test_create_request_fans_out_to_multiple_targets_capped_at_setting(admin_session):
    # NOTE: pre-unified-swap-requests, create_request fanned out into one
    # SwapRequest row per target. It now returns a single SwapRequest with
    # one SwapCandidate per target instead — see create_request/
    # _add_invited_candidate in swaps.py. The too-many-targets cap and the
    # resulting per-target rows both still exist, just as candidates.
    requester, (s1, s2, s3), assignment = _seed_multi_target(admin_session, n=3)
    set_setting(admin_session, "swaps.max_specific_targets", 2, actor_id=None)
    admin_session.flush()

    try:
        svc.create_request(
            admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, target_soldier_ids=[s1.id, s2.id, s3.id], reason=None,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "too_many_targets"

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[s1.id, s2.id], reason=None,
    )
    assert req.status == "open"
    candidates = {c.soldier_id: c for c in admin_session.execute(
        select(SwapCandidate).where(SwapCandidate.swap_request_id == req.id)
    ).scalars().all()}
    assert set(candidates) == {s1.id, s2.id}
    assert all(c.status == "pending" for c in candidates.values())


def test_claiming_one_targeted_request_cancels_siblings(admin_session):
    # NOTE: "siblings" used to be separate SwapRequest rows fanned out per
    # target; now they're SwapCandidate rows sharing one SwapRequest.
    # Claiming (and finalizing) one candidate cancels the others — same
    # observable behavior, different underlying shape.
    requester, (s1, s2), assignment = _seed_multi_target(admin_session, n=2)
    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[s1.id, s2.id], reason=None,
    )
    admin_session.flush()

    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=s1.id)
    admin_session.flush()
    admin_session.refresh(req)
    s2_candidate = _candidate(admin_session, req.id, s2.id)
    assert req.status == "applied"
    assert s2_candidate.status == "cancelled"


def test_create_request_rejects_second_open_request_for_same_duty_via_fan_out(admin_session):
    """The double-cover risk the old fan-out design could hit — a second,
    independently-created request for the same (duty_assignment, requester)
    while the first is still live — is now blocked structurally by
    create_request's own single-open-request-per-(requester, duty) guard
    (see the "already_pending" check and its unique-index backstop in
    swaps.py), rather than needing a separate finalize-time safety net.
    Full coverage of that guard lives in
    test_create_request_rejects_second_open_request_for_same_duty in
    test_swaps_service.py; this just confirms it also fires for the
    multi-target fan-out entry point."""
    requester, (s1, s2), assignment = _seed_multi_target(admin_session, n=2)

    svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=s1.id, reason=None,
    )
    admin_session.flush()

    try:
        svc.create_request(
            admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
            target_soldier_id=s2.id, reason=None,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "already_pending"


def test_create_request_rejects_empty_target_list(admin_session):
    a, b, assignment = _seed(admin_session)
    try:
        svc.create_request(
            admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, target_soldier_ids=[], reason=None,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "no_targets_specified"
