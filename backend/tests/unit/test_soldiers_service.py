from __future__ import annotations

import json
from datetime import date
import pytest


from app.services.soldiers import SoldierError, approve_field_update, submit_field_update
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


    s = create_soldier(admin_session, personal_number="7700004")
    s.gender = "male"
    with pytest.raises(SoldierError) as exc:
        submit_field_update(
            admin_session, soldier_id=s.id, field_name="gender",
            new_value=" male ", actor_id=s.id,
        )
    assert str(exc.value) == "same_value"


def test_submit_different_gender_allowed(admin_session):
    s = create_soldier(admin_session, personal_number="7700005")
    s.gender = "male"
    req = submit_field_update(
        admin_session, soldier_id=s.id, field_name="gender",
        new_value="female", actor_id=s.id,
    )
    admin_session.commit()
    assert req.status == "pending"


def test_submit_same_rank_json_rejected(admin_session):
    s = create_soldier(admin_session, personal_number="7700006")
    s.rank = "סמל"
    s.rank_track = "enlisted"
    with pytest.raises(SoldierError) as exc:
        submit_field_update(
            admin_session, soldier_id=s.id, field_name="rank",
            new_value=json.dumps({"rank": "סמל", "rank_track": "enlisted"}),
            actor_id=s.id,
        )
    assert str(exc.value) == "same_value"


def test_submit_rank_with_changed_track_allowed(admin_session):
    s = create_soldier(admin_session, personal_number="7700007")
    s.rank = "סמל"
    s.rank_track = "enlisted"
    req = submit_field_update(
        admin_session, soldier_id=s.id, field_name="rank",
        new_value=json.dumps({"rank": "סמל", "rank_track": "officer"}),
        actor_id=s.id,
    )
    admin_session.commit()
    assert req.status == "pending"


def test_submit_same_license_rejected(admin_session):
    s = create_soldier(admin_session, personal_number="7700008")
    s.has_military_driving_license = True
    s.military_driving_license_expiry = date(2027, 1, 1)
    with pytest.raises(SoldierError) as exc:
        submit_field_update(
            admin_session, soldier_id=s.id, field_name="military_driving_license",
            new_value=json.dumps({"has_license": True, "expiry_date": "2027-01-01"}),
            actor_id=s.id,
        )
    assert str(exc.value) == "same_value"


def test_submit_same_date_rejected_and_empty_matches_none(admin_session):
    s = create_soldier(admin_session, personal_number="7700009")
    s.discharge_date = date(2027, 3, 15)
    with pytest.raises(SoldierError):
        submit_field_update(
            admin_session, soldier_id=s.id, field_name="discharge_date",
            new_value="2027-03-15", actor_id=s.id,
        )
    no_date = create_soldier(admin_session, personal_number="7700010")
    with pytest.raises(SoldierError):
        submit_field_update(
            admin_session, soldier_id=no_date.id, field_name="last_mitvahim_date",
            new_value="", actor_id=no_date.id,
        )


def test_submit_new_date_allowed(admin_session):
    s = create_soldier(admin_session, personal_number="7700011")
    s.discharge_date = date(2027, 3, 15)
    req = submit_field_update(
        admin_session, soldier_id=s.id, field_name="discharge_date",
        new_value="2028-01-01", actor_id=s.id,
    )
    admin_session.commit()
    assert req.previous_value == "2027-03-15"


def test_submit_same_phone_rejected(admin_session):
    s = create_soldier(admin_session, personal_number="7700012")
    s.phone = "050-1234567"
    with pytest.raises(SoldierError):
        submit_field_update(
            admin_session, soldier_id=s.id, field_name="phone",
            new_value=" 050-1234567 ", actor_id=s.id,
        )
