import pytest

from app.services.identity import derive_ad_username, normalize_email


@pytest.mark.parametrize(
    ("raw", "canonical", "username"),
    [
        (None, None, None),
        ("", None, None),
        (" \t ", None, None),
        (" Dude@Gmail.COM ", "dude@gmail.com", "dude"),
        ("First.Last@Example.COM", "first.last@example.com", "first.last"),
        ("a_b-c!d@example.org", "a_b-c!d@example.org", "a_b-c!d"),
        ("a" * 20 + "@example.org", "a" * 20 + "@example.org", "a" * 20),
    ],
)
def test_normalization_and_derivation(raw, canonical, username):
    assert normalize_email(raw) == canonical
    assert derive_ad_username(raw) == username
    assert normalize_email(canonical) == canonical
    assert derive_ad_username(canonical) == username


@pytest.mark.parametrize(
    "raw",
    [
        "no-at-sign",
        "@example.com",
        "name@",
        "name@@example.com",
        "name@example",
        "name@-example.com",
        "name@example..com",
        ".name@example.com",
        "name..part@example.com",
        "name @example.com",
        "name@example .com",
        "nämé@example.com",
        "name@exämple.com",
        "K@example.com",
        "name@Kexample.com",
    ],
)
def test_invalid_addresses_are_rejected_by_both_functions(raw):
    with pytest.raises(ValueError):
        normalize_email(raw)
    with pytest.raises(ValueError):
        derive_ad_username(raw)


@pytest.mark.parametrize("local", ["name+tag", "name=tag", "name,tag"])
def test_forbidden_sam_account_name_punctuation_is_not_removed(local):
    raw = f"{local}@example.com"
    with pytest.raises(ValueError):
        normalize_email(raw)
    with pytest.raises(ValueError):
        derive_ad_username(raw)


def test_sam_account_name_length_limit_is_20_characters():
    raw = "a" * 21 + "@example.com"
    with pytest.raises(ValueError):
        normalize_email(raw)
    with pytest.raises(ValueError):
        derive_ad_username(raw)
