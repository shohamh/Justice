from __future__ import annotations

import json
from datetime import date

from app.services.soldiers import approve_field_update, submit_field_update
from tests.helpers import create_soldier


def test_submit_military_license_captures_previous_value(admin_session):
    s = create_soldier(admin_session, personal_number="7700001")
    req = submit_field_update(
        admin_session,
        soldier_id=s.id,
        field_name="military_driving_license",
        new_value=json.dumps({"has_license": True, "expiry_date": "2027-01-01"}),
        actor_id=s.id,
    )
    admin_session.commit()
    assert json.loads(req.previous_value) == {"has_license": False, "expiry_date": None}


def test_approve_military_license_sets_both_columns(admin_session):
    s = create_soldier(admin_session, personal_number="7700002")
    req = submit_field_update(
        admin_session,
        soldier_id=s.id,
        field_name="military_driving_license",
        new_value=json.dumps({"has_license": True, "expiry_date": "2027-06-15"}),
        actor_id=s.id,
    )
    admin_session.flush()
    approve_field_update(admin_session, update=req, actor_id=s.id)
    admin_session.commit()
    admin_session.refresh(s)
    assert s.has_military_driving_license is True
    assert s.military_driving_license_expiry == date(2027, 6, 15)


def test_approve_military_license_with_no_expiry(admin_session):
    s = create_soldier(admin_session, personal_number="7700003")
    req = submit_field_update(
        admin_session,
        soldier_id=s.id,
        field_name="military_driving_license",
        new_value=json.dumps({"has_license": True, "expiry_date": None}),
        actor_id=s.id,
    )
    admin_session.flush()
    approve_field_update(admin_session, update=req, actor_id=s.id)
    admin_session.commit()
    admin_session.refresh(s)
    assert s.has_military_driving_license is True
    assert s.military_driving_license_expiry is None
