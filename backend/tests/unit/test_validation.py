from __future__ import annotations

import pytest

from app.validation import is_valid_israeli_phone


@pytest.mark.parametrize("phone", [
    "0501234567",
    "050-1234567",
    "050 1234567",
    "+972501234567",
    "+972-50-1234567",
    "972501234567",
    "021234567",
    "02-1234567",
    "081234567",
])
def test_is_valid_israeli_phone_accepts(phone: str) -> None:
    assert is_valid_israeli_phone(phone) is True


@pytest.mark.parametrize("phone", [
    "",
    "123",
    "05012345",
    "050123456789",
    "0601234567",
    "abcdefghij",
    "+1-555-123-4567",
])
def test_is_valid_israeli_phone_rejects(phone: str) -> None:
    assert is_valid_israeli_phone(phone) is False
