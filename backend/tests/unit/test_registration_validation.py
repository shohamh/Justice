import pytest

from app.services.registration import validate_full_name, validate_personal_constraint


def test_full_name_requires_two_words():
    with pytest.raises(ValueError, match="full_name_requires_two_words"):
        validate_full_name("ישראל")


def test_full_name_allows_whitespace_between_two_words():
    validate_full_name("ישראל   ישראלי")


def test_full_name_is_limited_to_100_characters():
    with pytest.raises(ValueError, match="full_name_too_long"):
        validate_full_name(f"ישראל {'א' * 96}")


def test_personal_constraint_requires_reason():
    with pytest.raises(ValueError, match="constraint_missing_fields"):
        validate_personal_constraint({"start_date": "2026-01-01", "end_date": "2026-01-02", "reason": "  "})
