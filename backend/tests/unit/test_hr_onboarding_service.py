from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from app.db.models import ExemptionRequest, ExemptionType, PersonalConstraint, SoldierHrProfile
from app.services.hr_onboarding import OnboardingError, complete_first_login_onboarding
from tests.helpers import create_soldier


def _exemption_type(session, *, name: str = "פטור בדיקה", is_commander_exemption: bool = False) -> ExemptionType:
    et = ExemptionType(name=name, is_commander_exemption=is_commander_exemption, is_global=True)
    session.add(et)
    session.flush()
    return et


def _eligible_soldier(session, *, personal_number: str):
    """An HR-synced, not-yet-onboarded soldier — the only population eligible
    to call complete_first_login_onboarding (C3's eligibility gate)."""
    soldier = create_soldier(session, personal_number=personal_number, must_change_password=True)
    session.add(SoldierHrProfile(personal_number=personal_number, raw_dto={}, soldier_id=soldier.id))
    session.commit()
    return soldier


def test_sets_direct_fields_and_marks_completed(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-1")

    result = complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type="vegetarian", food_constraints="no nuts",
        last_mitvahim_date=date(2026, 1, 1), last_alal_date=date(2026, 2, 1),
        exemption_requests=[], personal_constraints=[],
    )
    admin_session.commit()

    assert result.food_type == "vegetarian"
    assert result.food_constraints == "no nuts"
    assert result.last_mitvahim_date == date(2026, 1, 1)
    assert result.last_alal_date == date(2026, 2, 1)
    assert result.hr_onboarding_completed_at is not None


def test_creates_pending_exemption_requests(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-2")
    et = _exemption_type(admin_session)
    admin_session.commit()

    complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
        exemption_requests=[{"exemption_type_id": str(et.id), "reason": "test reason"}],
        personal_constraints=[],
    )
    admin_session.commit()

    rows = admin_session.query(ExemptionRequest).filter_by(soldier_id=soldier.id).all()
    assert len(rows) == 1
    assert rows[0].status == "pending_commander"
    assert rows[0].exemption_type_id == et.id


def test_rejects_commander_exemption_type(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-3")
    et = _exemption_type(admin_session, is_commander_exemption=True)
    admin_session.commit()

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": str(et.id)}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "commander_exemption_not_requestable"


def test_creates_pending_personal_constraints(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-4")

    complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
        exemption_requests=[],
        personal_constraints=[{"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 5), "reason": "test"}],
    )
    admin_session.commit()

    rows = admin_session.query(PersonalConstraint).filter_by(soldier_id=soldier.id).all()
    assert len(rows) == 1
    assert rows[0].status == "pending_commander"


def test_rejects_invalid_personal_constraint(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-5")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[],
            personal_constraints=[{"start_date": date(2026, 1, 1), "end_date": None, "reason": ""}],
        )
    assert str(exc_info.value) == "constraint_missing_fields"


def test_rejects_exemption_request_missing_type_id(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-6")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": None}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "exemption_missing_fields"


def test_rejects_exemption_request_end_date_without_start_date(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-7")
    et = _exemption_type(admin_session)
    admin_session.commit()

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": str(et.id), "end_date": date(2026, 1, 5)}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "start_date_required"


def test_rejects_exemption_request_with_malformed_type_id(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-8")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": "not-a-uuid"}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "exemption_missing_fields"


def test_rejects_exemption_request_with_unknown_type_id(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-9")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": str(uuid.uuid4())}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "exemption_type_not_found"


def test_rejects_exemption_request_with_bad_date_range(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-10")
    et = _exemption_type(admin_session)
    admin_session.commit()

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{
                "exemption_type_id": str(et.id),
                "start_date": date(2026, 1, 10),
                "end_date": date(2026, 1, 5),
            }],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "bad_date_range"


# --- C3 fixes: eligibility gate, food_type validation, date validation, notifications ---


def test_rejects_soldier_with_no_hr_profile(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-11")  # not HR-linked

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[], personal_constraints=[],
        )
    assert str(exc_info.value) == "not_eligible"


def test_rejects_soldier_who_already_onboarded(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-12")
    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    admin_session.commit()

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[], personal_constraints=[],
        )
    assert str(exc_info.value) == "not_eligible"


def test_rejects_invalid_food_type(admin_session):
    soldier = _eligible_soldier(admin_session, personal_number="onb-13")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type="not_a_real_food_type", food_constraints=None,
            last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[], personal_constraints=[],
        )
    assert str(exc_info.value) == "invalid_food_type"


def test_accepts_all_valid_food_types(admin_session):
    for i, food_type in enumerate(
        ("regular", "vegetarian", "vegan", "gluten_free", "kosher_le_mehadrin")
    ):
        soldier = _eligible_soldier(admin_session, personal_number=f"onb-14-{i}")
        result = complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=food_type, food_constraints=None,
            last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[], personal_constraints=[],
        )
        admin_session.commit()
        assert result.food_type == food_type


def test_does_not_reject_onboarding_for_pre_existing_bad_hr_dates(admin_session):
    """Round-2 review Important #1: this form only sets last_mitvahim_date/
    last_alal_date. It must NOT run validate_soldier_dates against the whole
    soldier row — that checks rank/enlistment_date/unit_join_date/
    enrolled_at/discharge_date/mandatory_end_date/is_career, none of which
    this form touches. Those come from HR sync with no cross-field
    validation on the way in, so a soldier whose HR-sourced record already
    has e.g. discharge_date <= enlistment_date must still be able to
    complete onboarding — otherwise they're permanently locked out with no
    way to fix HR's own data through this form."""
    soldier = _eligible_soldier(admin_session, personal_number="onb-15")
    soldier.enlistment_date = date(2025, 1, 1)
    soldier.discharge_date = date(2024, 1, 1)  # inconsistent HR data, pre-existing
    admin_session.commit()

    result = complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type=None, food_constraints=None,
        last_mitvahim_date=date(2026, 1, 1), last_alal_date=None,
        exemption_requests=[], personal_constraints=[],
    )
    admin_session.commit()

    assert result.hr_onboarding_completed_at is not None
    assert result.last_mitvahim_date == date(2026, 1, 1)


def test_notifies_commanders_for_each_created_exemption_request(admin_session, monkeypatch):
    import app.services.hr_onboarding as hr_onboarding_module

    calls: list[dict] = []

    def _fake_notify(session, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(hr_onboarding_module, "notify_commanders_of_request", _fake_notify)

    soldier = _eligible_soldier(admin_session, personal_number="onb-16")
    et = _exemption_type(admin_session)
    admin_session.commit()

    complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
        exemption_requests=[{"exemption_type_id": str(et.id), "reason": "test reason"}],
        personal_constraints=[],
    )
    admin_session.commit()

    req = admin_session.query(ExemptionRequest).filter_by(soldier_id=soldier.id).one()
    assert len(calls) == 1
    assert calls[0]["soldier_id"] == soldier.id
    assert calls[0]["reference_id"] == req.id
    assert calls[0]["reference_type"] == "exemption_request"
    assert calls[0]["actor_id"] == soldier.id


def test_notifies_commanders_for_each_created_personal_constraint(admin_session, monkeypatch):
    """Round-2 review Important #2: PersonalConstraint rows created here must
    notify commanders too, same as ExemptionRequest rows do — otherwise they
    sit silently in the approval queue with nobody told."""
    import app.services.hr_onboarding as hr_onboarding_module

    calls: list[dict] = []

    def _fake_notify(session, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(hr_onboarding_module, "notify_commanders_of_request", _fake_notify)

    soldier = _eligible_soldier(admin_session, personal_number="onb-17")

    complete_first_login_onboarding(
        admin_session, soldier=soldier,
        food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
        exemption_requests=[],
        personal_constraints=[{"start_date": date(2026, 1, 1), "end_date": date(2026, 1, 5), "reason": "test"}],
    )
    admin_session.commit()

    constraint = admin_session.query(PersonalConstraint).filter_by(soldier_id=soldier.id).one()
    assert len(calls) == 1
    assert calls[0]["soldier_id"] == soldier.id
    assert calls[0]["reference_id"] == constraint.id
    assert calls[0]["reference_type"] == "personal_constraint"
    assert calls[0]["actor_id"] == soldier.id
