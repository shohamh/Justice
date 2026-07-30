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
