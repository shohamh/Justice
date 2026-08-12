from __future__ import annotations

MAX_EXEMPTION_FILE_BYTES = 10 * 1024 * 1024

ALLOWED_EXEMPTION_FILE_TYPES: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
}


class FileValidationError(ValueError):
    pass


def _magic_bytes_match(content_type: str, data: bytes) -> bool:
    return any(data[: len(prefix)] == prefix for prefix in ALLOWED_EXEMPTION_FILE_TYPES.get(content_type, []))


def validate_exemption_file(content_type: str, data: bytes) -> None:
    if content_type not in ALLOWED_EXEMPTION_FILE_TYPES:
        raise FileValidationError("invalid_file_type")
    if len(data) > MAX_EXEMPTION_FILE_BYTES:
        raise FileValidationError("file_too_large")
    if not _magic_bytes_match(content_type, data):
        raise FileValidationError("invalid_file_type")
