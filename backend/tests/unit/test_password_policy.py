import pytest

from app.services.soldiers import PasswordPolicyError, generate_temp_password, validate_password


def test_validate_rejects_short_password():
    with pytest.raises(PasswordPolicyError):
        validate_password("short")  # < 10 chars


def test_validate_accepts_long_password():
    validate_password("this-is-long-enough")  # no raise


def test_generated_temp_password_meets_policy():
    pw = generate_temp_password()
    assert len(pw) >= 10
    validate_password(pw)  # must not raise


def test_generated_temp_passwords_differ():
    assert generate_temp_password() != generate_temp_password()
