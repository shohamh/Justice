from datetime import date

from app.db.models import DutyAssignment, DutyDayOverride, DutyLocation, DutyType, Soldier, SwapRequest
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
