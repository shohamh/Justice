"""Restartable, verified migration of legacy file payloads to object storage."""
from __future__ import annotations

import json
import re
import struct
import zlib
from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256 as sha256_bytes
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from sqlalchemy.orm import object_session

from app.db.models import (
    BugReport,
    BugReportCommentAttachment,
    ExemptionRequestFile,
    GimelimAttachment,
    ImportSession,
    SoldierExemptionFile,
)
from app.logging_config import LOG_DIR
from app.storage.keys import FileClass, make_object_key
from app.storage.protocol import MaintenanceObjectStorage

MAX_LEGACY_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BackfillResult:
    status: str
    object_key: str | None = None
    sha256: str | None = None
    size: int | None = None
    error_code: str | None = None


class BackfillError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class _Payload:
    file_class: FileClass
    source_attr: str | None
    content_type_attr: str | None
    key_attr: str
    hash_attr: str
    allowed_types: tuple[str, ...] = ()


_PAYLOADS: dict[type[Any], _Payload] = {
    SoldierExemptionFile: _Payload("soldier_exemption", "data", "content_type", "storage_key", "storage_sha256", ("application/pdf", "image/jpeg", "image/png", "image/gif")),
    ExemptionRequestFile: _Payload("exemption_request", "data", "content_type", "storage_key", "storage_sha256", ("application/pdf", "image/jpeg", "image/png", "image/gif")),
    GimelimAttachment: _Payload("gimelim", "data", "content_type", "storage_key", "storage_sha256", ("application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp")),
    BugReportCommentAttachment: _Payload("bug_report_comment", "data", "content_type", "storage_key", "storage_sha256", ("application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp")),
    BugReport: _Payload("bug_report_screenshot", "screenshot", None, "storage_key", "storage_sha256", ("image/png",)),
    ImportSession: _Payload("import_workbook", "raw_excel", None, "storage_key", "storage_sha256"),
}

_IMAGE_SIGNATURES: dict[str, bytes | tuple[bytes, ...]] = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": b"RIFF",
}


def _validate_png(data: bytes) -> bool:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    pos = 8
    chunks: list[bytes] = []
    saw_header = saw_end = saw_idat = False
    width = height = bit_depth = color_type = 0
    while pos + 12 <= len(data):
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        end = pos + 12 + size
        if end > len(data):
            return False
        kind = data[pos + 4:pos + 8]
        value = data[pos + 8:pos + 8 + size]
        crc = struct.unpack(">I", data[pos + 8 + size:end])[0]
        if zlib.crc32(kind + value) & 0xFFFFFFFF != crc:
            return False
        if not saw_header and kind != b"IHDR":
            return False
        if kind == b"IHDR":
            if saw_header or size != 13:
                return False
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", value)
            if not width or not height or width * height > 100_000_000 or compression or filtering or interlace:
                return False
            valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if color_type not in valid_depths or bit_depth not in valid_depths[color_type]:
                return False
            saw_header = True
        elif kind == b"IDAT":
            saw_idat = True
            chunks.append(value)
        elif kind == b"IEND":
            saw_end = size == 0 and end == len(data)
            break
        pos = end
    if not (saw_header and saw_idat and saw_end):
        return False
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    expected_row_bytes = (width * channels * bit_depth + 7) // 8
    expected_size = height * (expected_row_bytes + 1)
    if expected_size > MAX_LEGACY_BYTES:
        return False
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(b"".join(chunks), MAX_LEGACY_BYTES + 1)
        if len(decoded) != expected_size or not decompressor.eof or decompressor.unused_data:
            return False
        return all(decoded[row * (expected_row_bytes + 1)] <= 4 for row in range(height))
    except zlib.error:
        return False


def _validate_payload(content_type: str, data: bytes, *, workbook: bool = False) -> bool:
    if not data or len(data) > MAX_LEGACY_BYTES:
        return False
    if workbook:
        if not data.startswith(b"PK"):
            return False
        try:
            with ZipFile(__import__("io").BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > 4096 or not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(archive.namelist()):
                    return False
                if sum(item.file_size for item in infos) > MAX_LEGACY_BYTES:
                    return False
                for item in infos:
                    if item.file_size > MAX_LEGACY_BYTES:
                        return False
                    if item.file_size and (item.compress_size == 0 or item.file_size > item.compress_size * 100):
                        return False
                    if re.search(r"(^|/)vbaProject\.bin$", item.filename, re.IGNORECASE):
                        return False
                    if "externalLinks/" in item.filename:
                        return False
                    if item.filename.endswith(".rels"):
                        if item.file_size > 2 * 1024 * 1024:
                            return False
                        relationships = archive.read(item)
                        if re.search(rb"(?i)TargetMode\s*=\s*['\"]External['\"]", relationships):
                            return False
                content_types = archive.read("[Content_Types].xml")
                return b"macroEnabled" not in content_types and b"vbaProject" not in content_types
        except (BadZipFile, OSError, RuntimeError):
            return False
    if content_type == "application/pdf":
        return data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]
    if content_type == "image/png":
        return _validate_png(data)
    if content_type == "image/jpeg":
        return data.startswith(_IMAGE_SIGNATURES[content_type]) and data.endswith(b"\xff\xd9")
    if content_type == "image/gif":
        return data.startswith(_IMAGE_SIGNATURES[content_type]) and data.endswith(b";")
    if content_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP" and struct.unpack("<I", data[4:8])[0] + 8 == len(data)
    return False


def _legacy_payload(record: Any, payload_name: str, config: _Payload) -> tuple[bytes, str]:
    if payload_name == "json_mirror" and isinstance(record, BugReport):
        path_value = record.json_file_path
        if not path_value:
            raise BackfillError("source_unreachable")
        try:
            mirror_root = (LOG_DIR / "bug_reports").resolve()
            source_path = Path(path_value).resolve(strict=True)
            if not source_path.is_relative_to(mirror_root) or not source_path.is_file():
                raise OSError("mirror_source_outside_configured_root")
            if source_path.stat().st_size > MAX_LEGACY_BYTES:
                raise BackfillError("invalid_payload")
            data = source_path.read_bytes()
        except BackfillError:
            raise
        except OSError as exc:
            raise BackfillError("source_unreachable") from exc
        try:
            parsed = json.loads(data)
            if not isinstance(parsed, dict):
                raise ValueError
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise BackfillError("invalid_payload") from exc
        return data, "application/json"
    if payload_name != "main":
        raise BackfillError("unsupported_payload")
    if config.source_attr is None:
        raise BackfillError("unsupported_payload")
    data = getattr(record, config.source_attr, None)
    if not isinstance(data, bytes):
        raise BackfillError("source_unreachable")
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if isinstance(record, ImportSession) else (getattr(record, config.content_type_attr) if config.content_type_attr else "image/png")
    if not isinstance(record, ImportSession) and content_type not in config.allowed_types:
        raise BackfillError("unsupported_format")
    return data, content_type


def validate_legacy_record(record: Any, *, payload: str = "main") -> tuple[int, str]:
    """Validate source bytes without writing an object; returns size and stable class."""
    config = _PAYLOADS.get(type(record))
    if config is None:
        raise BackfillError("unsupported_record")
    if payload == "json_mirror":
        if not isinstance(record, BugReport):
            raise BackfillError("unsupported_payload")
        data, content_type = _legacy_payload(record, payload, config)
        try:
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise BackfillError("invalid_payload") from exc
        return len(data), content_type
    data, content_type = _legacy_payload(record, payload, config)
    if not _validate_payload(content_type, data, workbook=isinstance(record, ImportSession)):
        raise BackfillError("invalid_payload")
    return len(data), content_type


def backfill_record(storage: MaintenanceObjectStorage, record: Any, *, payload: str = "main") -> BackfillResult:
    """Validate and copy one known legacy record, then persist its verified key."""
    config = _PAYLOADS.get(type(record))
    if config is None or getattr(record, "id", None) is None:
        raise BackfillError("unsupported_record")
    if payload == "json_mirror":
        if not isinstance(record, BugReport):
            raise BackfillError("unsupported_payload")
        file_class: FileClass = "bug_report_json_mirror"
        key_attr, hash_attr = "json_mirror_storage_key", "json_mirror_sha256"
    else:
        file_class = config.file_class
        key_attr, hash_attr = config.key_attr, config.hash_attr
    current_key = getattr(record, key_attr, None)
    current_hash = getattr(record, hash_attr, None)
    if current_key and current_hash:
        current_size = getattr(record, "storage_size", None) if payload == "main" else None
        existing = storage.head(key=current_key)
        size_verified = payload == "json_mirror" or (current_size is not None and existing is not None and existing.size == current_size)
        if existing and existing.sha256 == current_hash and size_verified:
            return BackfillResult("already_verified", current_key, current_hash, existing.size)
    data, content_type = _legacy_payload(record, payload, config)
    if payload == "json_mirror":
        try:
            parsed = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackfillError("invalid_payload") from exc
        if not isinstance(parsed, dict):
            raise BackfillError("invalid_payload")
    elif not _validate_payload(content_type, data, workbook=isinstance(record, ImportSession)):
        raise BackfillError("invalid_payload")
    digest = sha256_bytes(data).hexdigest()
    object_key = make_object_key(file_class, record.id)
    try:
        written = storage.put_bytes(key=object_key, data=data, content_type=content_type, sha256=digest)
        body, content_length = storage.open_read(key=object_key)
        try:
            readback = body.read(MAX_LEGACY_BYTES + 1)
        finally:
            body.close()
        if len(readback) > MAX_LEGACY_BYTES or content_length != len(data) or len(readback) != len(data) or sha256_bytes(readback).hexdigest() != digest:
            raise BackfillError("readback_mismatch")
        if written.key != object_key or written.size != len(data) or written.sha256 != digest:
            raise BackfillError("write_metadata_mismatch")
        if written.encryption_algorithm is None:
            # Local MinIO may not return SSE metadata; production preflight enforces it separately.
            pass
    except Exception as exc:
        with suppress(Exception):
            storage.delete(key=object_key)
        if isinstance(exc, BackfillError):
            raise
        raise BackfillError("storage_operation_failed") from exc
    old_values = (getattr(record, key_attr, None), getattr(record, hash_attr, None), getattr(record, "storage_size", None))
    setattr(record, key_attr, object_key)
    setattr(record, hash_attr, digest)
    if payload == "main":
        record.storage_size = len(data)
    session = object_session(record)
    if session is not None:
        try:
            session.commit()
        except Exception as exc:
            session.rollback()
            setattr(record, key_attr, old_values[0])
            setattr(record, hash_attr, old_values[1])
            if payload == "main":
                record.storage_size = old_values[2]
            with suppress(Exception):
                storage.delete(key=object_key)
            raise BackfillError("database_commit_failed") from exc
    return BackfillResult("migrated", object_key, digest, len(data))
