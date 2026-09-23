from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.db.models import ExemptionRequest, ExemptionType, PersonalConstraint
from app.services.hr_onboarding import OnboardingError, complete_first_login_onboarding
from tests.helpers import create_soldier


def _exemption_type(session, *, name: str = "פטור בדיקה", is_commander_exemption: bool = False) -> ExemptionType:
    et = ExemptionType(name=name, is_commander_exemption=is_commander_exemption, is_global=True)
    session.add(et)
    session.flush()
    return et


def test_sets_direct_fields_and_marks_completed(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-1")

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
    soldier = create_soldier(admin_session, personal_number="onb-2")
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
    soldier = create_soldier(admin_session, personal_number="onb-3")
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
    soldier = create_soldier(admin_session, personal_number="onb-4")

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
    soldier = create_soldier(admin_session, personal_number="onb-5")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[],
            personal_constraints=[{"start_date": date(2026, 1, 1), "end_date": None, "reason": ""}],
        )
    assert str(exc_info.value) == "constraint_missing_fields"


def test_rejects_exemption_request_missing_type_id(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-6")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": None}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "exemption_missing_fields"


def test_rejects_exemption_request_end_date_without_start_date(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-7")
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
    soldier = create_soldier(admin_session, personal_number="onb-8")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": "not-a-uuid"}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "exemption_missing_fields"


def test_rejects_exemption_request_with_unknown_type_id(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-9")

    with pytest.raises(OnboardingError) as exc_info:
        complete_first_login_onboarding(
            admin_session, soldier=soldier,
            food_type=None, food_constraints=None, last_mitvahim_date=None, last_alal_date=None,
            exemption_requests=[{"exemption_type_id": str(uuid.uuid4())}],
            personal_constraints=[],
        )
    assert str(exc_info.value) == "exemption_type_not_found"


def test_rejects_exemption_request_with_bad_date_range(admin_session):
    soldier = create_soldier(admin_session, personal_number="onb-10")
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
