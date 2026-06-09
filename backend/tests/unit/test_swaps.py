from datetime import date
from decimal import Decimal

from app.db.models import DutyAssignment, DutyDayOverride, DutyLocation, DutyType, Soldier, SwapRequest, SystemSetting
from app.services import swaps as svc
from app.services.settings_loader import set_setting


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
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 10), status="published",
    )
    session.add(assignment)
    session.flush()
    return a, b, assignment


def test_create_open_request(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="busy", actor_id=a.id,
    )
    assert req.status == "open"
    assert req.target_soldier_id is None


def test_create_direct_request(admin_session):
    a, b, assignment = _seed(admin_session)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=b.id, reason="cover me", actor_id=a.id,
    )
    assert req.status == "open"
    assert req.target_soldier_id == b.id


def test_cannot_request_others_duty(admin_session):
    a, b, assignment = _seed(admin_session)
    try:
        svc.create_request(
            admin_session, requesting_soldier_id=b.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, reason="x", actor_id=b.id,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "not_your_duty"


def test_claim_auto_applies_when_approval_off(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id,
    )
    admin_session.flush()
    out = svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    assert out.status == "applied"
    assert out.covering_soldier_id == b.id
    ov = admin_session.get(DutyDayOverride, out.resulting_override_id)
    assert ov is not None
    assert ov.effective_soldier_id == b.id
    assert ov.reason == "replacement"


def test_claim_queues_when_approval_on(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id,
    )
    admin_session.flush()
    out = svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    assert out.status == "pending_approval"
    assert out.resulting_override_id is None


def test_two_sided_approval_applies_only_after_both(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id,
    )
    admin_session.flush()
    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()

    svc.approve_side(admin_session, request_id=req.id, side="requester", actor_id=None)
    assert admin_session.get(SwapRequest, req.id).status == "pending_approval"  # still waiting

    out = svc.approve_side(admin_session, request_id=req.id, side="covering", actor_id=None)
    assert out.status == "applied"
    assert out.resulting_override_id is not None


def test_reject_sets_status_and_no_override(admin_session):
    a, b, assignment = _seed(admin_session)
    set_setting(admin_session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        admin_session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, reason="x", actor_id=a.id,
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
        target_soldier_id=None, reason="x", actor_id=a.id,
    )
    admin_session.flush()
    svc.cancel_request(admin_session, request_id=req.id, actor_id=a.id)
    assert admin_session.get(SwapRequest, req.id).status == "cancelled"


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
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 7),
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
    _reserve_assignment(admin_session, taker.id, dt.id, loc.id, date(2026, 8, 10), date(2026, 8, 23))
    try:
        svc.take_free(admin_session, assignment_id=reserve_a.id, covering_soldier_id=taker.id, actor_id=taker.id)
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "reserve_cap_exceeded:21/14"


def test_take_free_reserve_succeeds_under_cap(admin_session):
    owner, taker, reserve_a, _, _ = _seed_with_reserve(admin_session)
    # No existing reserves for taker → under cap
    result = svc.take_free(admin_session, assignment_id=reserve_a.id, covering_soldier_id=taker.id, actor_id=taker.id)
    assert result.status in ("open", "applied")


def test_take_free_primary_unaffected_by_reserve_setting(admin_session):
    # Disabling allow_take_free must NOT block take-free on primary assignments
    a, b, assignment = _seed(admin_session)  # _seed creates a primary assignment
    admin_session.add(SystemSetting(key="reserves.allow_take_free", value=False))
    admin_session.flush()
    # Should succeed — primary assignment, not reserve
    result = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    assert result is not None
