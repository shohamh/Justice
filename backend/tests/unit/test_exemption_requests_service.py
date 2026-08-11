import pytest
from datetime import date, timedelta

from app.db.models import ExemptionType
from app.services.exemption_requests import ExemptionRequestError, submit_request
from tests.helpers import create_soldier


def _et(session, name="פטור-reason-test"):
    et = ExemptionType(name=name, is_commander_exemption=False)
    session.add(et)
    session.flush()
    return et


def test_submit_request_rejects_empty_reason(admin_session):
    s = create_soldier(admin_session, personal_number="7800001")
    et = _et(admin_session)
    with pytest.raises(ExemptionRequestError, match="reason_required"):
        submit_request(
            admin_session, soldier_id=s.id, exemption_type_id=et.id,
            start_date=date.today() + timedelta(days=1), reason="",
        )


def test_submit_request_rejects_whitespace_reason(admin_session):
    s = create_soldier(admin_session, personal_number="7800002")
    et = _et(admin_session, "פטור-reason-test-2")
    with pytest.raises(ExemptionRequestError, match="reason_required"):
        submit_request(
            admin_session, soldier_id=s.id, exemption_type_id=et.id,
            start_date=date.today() + timedelta(days=1), reason="   ",
        )


def test_submit_request_rejects_none_reason(admin_session):
    s = create_soldier(admin_session, personal_number="7800003")
    et = _et(admin_session, "פטור-reason-test-3")
    with pytest.raises(ExemptionRequestError, match="reason_required"):
        submit_request(
            admin_session, soldier_id=s.id, exemption_type_id=et.id,
            start_date=date.today() + timedelta(days=1), reason=None,
        )


def test_submit_request_accepts_real_reason(admin_session):
    s = create_soldier(admin_session, personal_number="7800004")
    et = _et(admin_session, "פטור-reason-test-4")
    req = submit_request(
        admin_session, soldier_id=s.id, exemption_type_id=et.id,
        start_date=date.today() + timedelta(days=1), reason="גב תפוס",
    )
    admin_session.commit()
    assert req.reason == "גב תפוס"


def test_submit_request_allows_permanent_with_no_dates(admin_session):
    s = create_soldier(admin_session, personal_number="7800005")
    et = _et(admin_session, "פטור-permanent-test")
    req = submit_request(
        admin_session, soldier_id=s.id, exemption_type_id=et.id,
        start_date=None, end_date=None, reason="פטור קבוע",
    )
    admin_session.commit()
    assert req.start_date is None
    assert req.end_date is None


def test_submit_request_rejects_end_date_without_start_date(admin_session):
    s = create_soldier(admin_session, personal_number="7800006")
    et = _et(admin_session, "פטור-permanent-test-2")
    with pytest.raises(ExemptionRequestError, match="start_date_required"):
        submit_request(
            admin_session, soldier_id=s.id, exemption_type_id=et.id,
            start_date=None, end_date=date.today() + timedelta(days=10), reason="סיבה",
        )


def test_approve_duty_manager_step_fills_start_date_for_permanent_request(admin_session):
    from app.services.exemption_requests import approve_commander_step, approve_duty_manager_step
    from app.db.models import SoldierExemption

    s = create_soldier(admin_session, personal_number="7800007")
    approver = create_soldier(admin_session, personal_number="7800008")
    et = _et(admin_session, "פטור-permanent-approve-test")
    req = submit_request(
        admin_session, soldier_id=s.id, exemption_type_id=et.id,
        start_date=None, end_date=None, reason="פטור קבוע",
    )
    admin_session.commit()

    approve_commander_step(admin_session, req.id, approved_by=approver.id)
    admin_session.commit()
    approve_duty_manager_step(admin_session, req.id, decided_by=approver.id)
    admin_session.commit()

    assert req.start_date == date.today()
    exemption = admin_session.query(SoldierExemption).filter_by(
        soldier_id=s.id, exemption_type_id=et.id,
    ).one()
    assert exemption.start_date == date.today()
    assert exemption.end_date is None
