import pytest

from app.services.soldiers import PasswordPolicyError, generate_temp_password, validate_password


def test_validate_rejects_short_password():
    with pytest.raises(PasswordPolicyError):
        validate_password("short")  # < 8 chars


def test_validate_accepts_long_password():
    validate_password("this-is-long-enough1!")  # no raise


def test_validate_rejects_password_without_symbol():
    with pytest.raises(PasswordPolicyError):
        validate_password("password123")


def test_validate_rejects_password_without_letter():
    with pytest.raises(PasswordPolicyError):
        validate_password("1234567!")


def test_validate_rejects_password_without_digit():
    with pytest.raises(PasswordPolicyError):
        validate_password("abcdefg!")


def test_generated_temp_password_meets_policy():
    pw = generate_temp_password()
    assert len(pw) >= 8
    validate_password(pw)  # must not raise


def test_generated_temp_passwords_differ():
    assert generate_temp_password() != generate_temp_password()
