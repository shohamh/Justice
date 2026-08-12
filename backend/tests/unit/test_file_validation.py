import pytest

from app.services.file_validation import FileValidationError, validate_exemption_file


def test_validate_exemption_file_accepts_valid_pdf():
    validate_exemption_file("application/pdf", b"%PDF-1.4 rest of file")


def test_validate_exemption_file_rejects_unknown_content_type():
    with pytest.raises(FileValidationError, match="invalid_file_type"):
        validate_exemption_file("application/zip", b"PK\x03\x04")


def test_validate_exemption_file_rejects_mismatched_magic_bytes():
    with pytest.raises(FileValidationError, match="invalid_file_type"):
        validate_exemption_file("application/pdf", b"not actually a pdf")


def test_validate_exemption_file_rejects_oversized_file():
    with pytest.raises(FileValidationError, match="file_too_large"):
        validate_exemption_file("application/pdf", b"%PDF" + b"0" * (10 * 1024 * 1024))
