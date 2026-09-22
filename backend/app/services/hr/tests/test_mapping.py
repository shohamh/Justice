from __future__ import annotations

from datetime import date

from app.services.eligibility import OFFICER_RANKS, derive_is_career
from app.services.hr.mapping import HeldForReview, MappedSoldierFields, map_hr_user
from app.services.hr.schemas import HrUser


def _hr_user(**overrides: object) -> HrUser:
    defaults: dict[str, object] = dict(
        full_name="ישראל ישראלי",
        personal_number="1234567",
        mail="israel@example.mil",
        phone="050-1112222",
        image_url="https://hr.example/img/1",
        gender="male",
        rank="טוראי",
        serv_type="chova",
        service_start_date="2024-01-01",
        end_hova_date="2026-01-01",
        service_end_date=None,
    )
    defaults.update(overrides)
    return HrUser(**defaults)


def test_map_hr_user_happy_path_enlisted():
    result = map_hr_user(_hr_user())
    assert isinstance(result, MappedSoldierFields)
    assert result.full_name == "ישראל ישראלי"
    assert result.personal_number == "1234567"
    assert result.email == "israel@example.mil"
    assert result.phone == "050-1112222"
    assert result.profile_picture_url == "https://hr.example/img/1"
    assert result.gender == "male"
    assert result.rank == "טוראי"
    assert result.rank_track == "חובה"
    assert result.is_officer is False
    assert result.enlistment_date == date(2024, 1, 1)
    assert result.mandatory_end_date == date(2026, 1, 1)
    assert result.discharge_date is None


def test_map_hr_user_officer_rank_sets_is_officer_and_kva_track():
    result = map_hr_user(_hr_user(rank=OFFICER_RANKS[0], serv_type="kva"))
    assert isinstance(result, MappedSoldierFields)
    assert result.is_officer is True
    assert result.rank_track == "קבע"


def test_map_hr_user_is_career_matches_derive_is_career_directly():
    hr = _hr_user(rank="רסל", serv_type="kva", end_hova_date="2020-01-01")
    result = map_hr_user(hr)
    assert isinstance(result, MappedSoldierFields)
    expected = derive_is_career("רסל", date(2020, 1, 1), None)
    assert result.is_career == expected
    assert result.is_career is True


def test_map_hr_user_unmappable_gender_held_for_review():
    result = map_hr_user(_hr_user(gender="unspecified"))
    assert isinstance(result, HeldForReview)
    assert result.personal_number == "1234567"
    assert any("gender" in r for r in result.reasons)


def test_map_hr_user_unmappable_rank_held_for_review():
    result = map_hr_user(_hr_user(rank="דרגה לא ידועה"))
    assert isinstance(result, HeldForReview)
    assert any("rank" in r for r in result.reasons)


def test_map_hr_user_unmappable_service_type_held_for_review():
    result = map_hr_user(_hr_user(serv_type="unknown_type"))
    assert isinstance(result, HeldForReview)
    assert any("servicType" in r for r in result.reasons)


def test_map_hr_user_unparseable_date_held_for_review():
    result = map_hr_user(_hr_user(service_start_date="not-a-date"))
    assert isinstance(result, HeldForReview)
    assert any("serviceStartDate" in r for r in result.reasons)


def test_map_hr_user_multiple_failures_all_reported():
    result = map_hr_user(_hr_user(gender="x", rank="y"))
    assert isinstance(result, HeldForReview)
    assert len(result.reasons) == 2


def test_map_hr_user_none_optional_fields_pass_through_as_none():
    result = map_hr_user(
        _hr_user(gender=None, rank=None, serv_type=None, mail=None, phone=None, image_url=None)
    )
    assert isinstance(result, MappedSoldierFields)
    assert result.gender is None
    assert result.rank is None
    assert result.rank_track is None
    assert result.is_officer is False
    assert result.email is None
    assert result.phone is None
    assert result.profile_picture_url is None


def test_map_hr_user_empty_personal_number_held_for_review():
    result = map_hr_user(_hr_user(personal_number=""))
    assert isinstance(result, HeldForReview)
    assert any("personal_number" in r for r in result.reasons)


def test_map_hr_user_empty_full_name_held_for_review():
    result = map_hr_user(_hr_user(full_name=""))
    assert isinstance(result, HeldForReview)
    assert any("full_name" in r for r in result.reasons)


def test_hr_owned_fields_contains_expected_names():
    from app.services.hr.mapping import HR_OWNED_FIELDS
    assert HR_OWNED_FIELDS == frozenset({
        "full_name", "personal_number", "email", "phone", "gender", "rank", "rank_track",
        "profile_picture_url", "enlistment_date", "mandatory_end_date", "discharge_date",
    })
