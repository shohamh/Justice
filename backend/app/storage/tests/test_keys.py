from uuid import UUID

import pytest

from app.storage.keys import make_object_key, validate_managed_key


@pytest.mark.parametrize(
    "file_class",
    [
        "soldier_exemption",
        "exemption_request",
        "gimelim",
        "bug_report_screenshot",
        "bug_report_comment",
        "import_workbook",
        "bug_report_json_mirror",
    ],
)
def test_generated_keys_have_only_class_and_uuid(file_class):
    object_id = UUID("01234567-89ab-4cde-8f01-23456789abcd")
    key = make_object_key(file_class, object_id)
    assert key == f"{file_class}/01234567-89ab-4cde-8f01-23456789abcd"
    assert validate_managed_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "../soldier_exemption/01234567-89ab-4cde-8f01-23456789abcd",
        "/soldier_exemption/01234567-89ab-4cde-8f01-23456789abcd",
        "soldier_exemption/../import_workbook/01234567-89ab-4cde-8f01-23456789abcd",
        "soldier_exemption/01234567-89ab-4cde-8f01-23456789abcd\x00",
        "unknown/01234567-89ab-4cde-8f01-23456789abcd",
        "https://storage.example/bucket/soldier_exemption/01234567-89ab-4cde-8f01-23456789abcd",
        "soldier_exemption/01234567-89ab-4cde-8f01-23456789abcd/file.pdf",
    ],
)
def test_rejects_unmanaged_keys(key):
    assert not validate_managed_key(key)
