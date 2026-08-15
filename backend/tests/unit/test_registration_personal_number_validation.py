import pytest

from app.services.registration import validate_personal_number


def test_personal_number_accepts_seven_or_eight_digits():
    validate_personal_number("1234567")
    validate_personal_number("12345678")


@pytest.mark.parametrize("value", ["123456", "123456789", "1234567A"])
def test_personal_number_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="personal_number_invalid"):
        validate_personal_number(value)
