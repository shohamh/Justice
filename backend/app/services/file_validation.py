from __future__ import annotations

import io
from zipfile import BadZipFile, ZipFile

MAX_EXEMPTION_FILE_BYTES = 10 * 1024 * 1024
MAX_GIMELIM_FILE_BYTES = 20 * 1024 * 1024
MAX_XLSX_BYTES = 20 * 1024 * 1024
MAX_XLSX_ZIP_ENTRIES = 4096
MAX_XLSX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_XLSX_COMPRESSION_RATIO = 100

ALLOWED_EXEMPTION_FILE_TYPES: dict[str, list[bytes]] = {
    "application/pdf": [b"%PDF"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
}
GIMELIM_FILE_TYPES: dict[str, list[bytes]] = {
    **ALLOWED_EXEMPTION_FILE_TYPES,
    "image/webp": [b"RIFF"],
}
BUG_REPORT_ATTACHMENT_TYPES = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
}


class FileValidationError(ValueError):
    pass


def _signature_match(content_type: str, data: bytes, allowed: dict[str, list[bytes]]) -> bool:
    return any(data.startswith(prefix) for prefix in allowed.get(content_type, []))


def validate_exemption_file(content_type: str, data: bytes) -> None:
    if content_type not in ALLOWED_EXEMPTION_FILE_TYPES:
        raise FileValidationError("invalid_file_type")
    if len(data) > MAX_EXEMPTION_FILE_BYTES:
        raise FileValidationError("file_too_large")
    if not _signature_match(content_type, data, ALLOWED_EXEMPTION_FILE_TYPES):
        raise FileValidationError("invalid_file_type")


def validate_gimelim_file(content_type: str, data: bytes) -> None:
    if content_type not in GIMELIM_FILE_TYPES:
        raise FileValidationError("invalid_file_type")
    if len(data) > MAX_GIMELIM_FILE_BYTES:
        raise FileValidationError("file_too_large")
    if not _signature_match(content_type, data, GIMELIM_FILE_TYPES):
        raise FileValidationError("invalid_file_type")
    if content_type == "image/webp" and (len(data) < 12 or data[8:12] != b"WEBP"):
        raise FileValidationError("invalid_file_type")


def validate_bug_report_attachment(content_type: str, data: bytes, *, max_bytes: int) -> None:
    if content_type not in BUG_REPORT_ATTACHMENT_TYPES:
        raise FileValidationError("invalid_file_type")
    if len(data) > max_bytes:
        raise FileValidationError("file_too_large")
    if not _signature_match(content_type, data, BUG_REPORT_ATTACHMENT_TYPES):
        raise FileValidationError("invalid_file_type")


def validate_xlsx(data: bytes) -> None:
    if len(data) > MAX_XLSX_BYTES:
        raise FileValidationError("file_too_large")
    if not data.startswith(b"PK\x03\x04"):
        raise FileValidationError("invalid_file_type")
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_XLSX_ZIP_ENTRIES:
                raise FileValidationError("invalid_xlsx_structure")
            expanded = 0
            for entry in entries:
                name = entry.filename.replace("\\", "/").casefold()
                if name.endswith("/vbaProject.bin") or "/vbaproject.bin" in name:
                    raise FileValidationError("invalid_xlsx_structure")
                if "externallinks/" in name:
                    raise FileValidationError("invalid_xlsx_structure")
                expanded += entry.file_size
                if expanded > MAX_XLSX_EXPANDED_BYTES:
                    raise FileValidationError("invalid_xlsx_structure")
                if entry.file_size and (entry.compress_size == 0 or entry.file_size / entry.compress_size > MAX_XLSX_COMPRESSION_RATIO):
                    raise FileValidationError("invalid_xlsx_structure")
                if name.endswith(".rels"):
                    content = archive.read(entry)
                    if b"TargetMode=\"External\"" in content or b"TargetMode='External'" in content:
                        raise FileValidationError("invalid_xlsx_structure")
                    if b"targetmode=\"external\"" in content.lower() or b"targetmode='external'" in content.lower():
                        raise FileValidationError("invalid_xlsx_structure")
            names = {entry.filename.casefold() for entry in entries}
            if "[content_types].xml" not in names or "xl/workbook.xml" not in names:
                raise FileValidationError("invalid_file_type")
            if any(entry.filename.casefold().endswith(".rels") for entry in entries):
                import xml.etree.ElementTree as ET

                for entry in entries:
                    if entry.filename.casefold().endswith(".rels"):
                        try:
                            root = ET.fromstring(archive.read(entry))
                        except ET.ParseError as exc:
                            raise FileValidationError("invalid_xlsx_structure") from exc
                        if any((node.attrib.get("TargetMode") or "").casefold() == "external" for node in root.iter()):
                            raise FileValidationError("invalid_xlsx_structure")
            # Force ZIP CRC verification before any workbook parser sees the file.
            for entry in entries:
                with archive.open(entry) as stream:
                    while stream.read(64 * 1024):
                        pass
    except BadZipFile as exc:
        raise FileValidationError("invalid_file_type") from exc
