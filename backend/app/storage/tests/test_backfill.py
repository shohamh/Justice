from __future__ import annotations

import struct
import zlib
from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.db.models import BugReport
from app.storage.backfill import BackfillError, backfill_record
from app.storage.protocol import StoredObject

RECORD_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
def png_bytes() -> bytes:
    def chunk(kind: bytes, value: bytes) -> bytes:
        body = kind + value
        return struct.pack(">I", len(value)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


PNG = png_bytes()


class FakeStorage:
    def __init__(self, *, corrupt: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_count = 0
        self.corrupt = corrupt
        self.deleted: list[str] = []
        self.fail_delete = False

    def put_bytes(self, *, key: str, data: bytes, content_type: str, sha256: str) -> StoredObject:
        self.put_count += 1
        self.objects[key] = data
        return StoredObject(key, len(data), sha256, "AES256", None)

    def open_read(self, *, key: str):
        data = self.objects[key]
        if self.corrupt:
            data += b"corrupt"
        return BytesIO(data), len(data)

    def head(self, *, key: str):
        data = self.objects.get(key)
        if data is None:
            return None
        return StoredObject(key, len(data), sha256(data).hexdigest(), "AES256", None)

    def delete(self, *, key: str) -> None:
        self.deleted.append(key)
        if self.fail_delete:
            raise RuntimeError("private provider detail")
        self.objects.pop(key, None)

    def iter_keys(self, *, prefix: str):
        yield from (key for key in self.objects if key.startswith(prefix))

    def iter_objects(self, *, prefix: str):
        from datetime import UTC, datetime, timedelta
        old = datetime.now(UTC) - timedelta(days=3)
        yield from ((key, old) for key in self.objects if key.startswith(prefix))


def image_report() -> BugReport:
    report = BugReport(description="test", severity="low", route="/", screenshot=PNG)
    report.id = RECORD_ID
    return report


def test_backfill_writes_stable_key_hash_and_size_and_is_idempotent() -> None:
    storage = FakeStorage()
    record = image_report()

    first = backfill_record(storage, record)
    second = backfill_record(storage, record)

    assert first.status == "migrated"
    assert first.object_key == f"bug_report_screenshot/{RECORD_ID}"
    assert record.storage_key == first.object_key
    assert record.storage_sha256 == sha256(PNG).hexdigest()
    assert record.storage_size == len(PNG)
    assert second.status == "already_verified"
    assert storage.put_count == 1


def test_backfill_keeps_legacy_bytes_when_readback_is_corrupt() -> None:
    storage = FakeStorage(corrupt=True)
    record = image_report()

    with pytest.raises(BackfillError, match="readback_mismatch"):
        backfill_record(storage, record)

    assert record.screenshot == PNG
    assert record.storage_key is None
    assert storage.deleted == [f"bug_report_screenshot/{RECORD_ID}"]


def test_backfill_rejects_unsupported_or_malformed_payload_before_upload() -> None:
    storage = FakeStorage()
    record = image_report()
    record.screenshot = b"not a png"

    with pytest.raises(BackfillError, match="invalid_payload"):
        backfill_record(storage, record)

    assert storage.put_count == 0
    assert record.storage_key is None
    assert record.screenshot == b"not a png"


def test_backfill_records_missing_json_mirror_path_as_failure(tmp_path) -> None:
    storage = FakeStorage()
    report = image_report()
    report.screenshot = None
    report.json_file_path = str(tmp_path / "missing.json")

    with pytest.raises(BackfillError, match="source_unreachable"):
        backfill_record(storage, report, payload="json_mirror")

    assert storage.put_count == 0
    assert report.json_mirror_storage_key is None


def test_failed_database_commit_cleans_up_object_and_preserves_legacy(monkeypatch) -> None:
    storage = FakeStorage()
    record = image_report()
    session = SimpleNamespace(
        commit=lambda: (_ for _ in ()).throw(RuntimeError("database detail")),
        rollback=lambda: None,
        flush=lambda: None,
    )
    monkeypatch.setattr("app.storage.backfill.object_session", lambda _: session)

    with pytest.raises(BackfillError, match="database_commit_failed"):
        backfill_record(storage, record)

    assert record.screenshot == PNG
    assert record.storage_key is None
    assert storage.deleted == [f"bug_report_screenshot/{RECORD_ID}"]


def test_restart_after_object_put_reuses_stable_object_and_creates_one_reference() -> None:
    storage = FakeStorage()
    record = image_report()
    expected_key = f"bug_report_screenshot/{RECORD_ID}"
    storage.objects[expected_key] = PNG

    result = backfill_record(storage, record)

    assert result.status == "migrated"
    assert list(storage.objects) == [expected_key]
    assert record.storage_key == expected_key


def test_failed_cleanup_is_discovered_as_orphan_by_reconciliation(monkeypatch) -> None:
    from app.storage.reconciliation import reconcile_storage

    storage = FakeStorage()
    storage.fail_delete = True
    record = image_report()
    session = SimpleNamespace(
        commit=lambda: (_ for _ in ()).throw(RuntimeError("database detail")),
        rollback=lambda: None,
        flush=lambda: None,
    )
    monkeypatch.setattr("app.storage.backfill.object_session", lambda _: session)

    with pytest.raises(BackfillError, match="database_commit_failed"):
        backfill_record(storage, record)

    report = reconcile_storage(SimpleNamespace(referenced_storage_keys=lambda: set()), storage)
    assert report.orphan_keys == [f"bug_report_screenshot/{RECORD_ID}"]
    assert storage.objects[f"bug_report_screenshot/{RECORD_ID}"] == PNG


def test_json_mirror_backfill_is_confined_to_configured_recovery_directory(tmp_path, monkeypatch) -> None:
    from app.storage import backfill as backfill_module

    root = tmp_path / "bug_reports"
    root.mkdir()
    mirror = root / "report.json"
    mirror.write_text('{"id":"example"}', encoding="utf-8")
    monkeypatch.setattr(backfill_module, "LOG_DIR", tmp_path)
    storage = FakeStorage()
    report = image_report()
    report.screenshot = None
    report.json_file_path = str(mirror)

    result = backfill_record(storage, report, payload="json_mirror")

    assert result.object_key == f"bug_report_json_mirror/{RECORD_ID}"
    assert report.json_mirror_storage_key == result.object_key

    outside = tmp_path / "outside.json"
    outside.write_text('{"id":"outside"}', encoding="utf-8")
    report.id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    report.json_mirror_storage_key = None
    report.json_mirror_sha256 = None
    report.json_file_path = str(outside)
    with pytest.raises(BackfillError, match="source_unreachable"):
        backfill_record(storage, report, payload="json_mirror")



def test_production_preflight_requires_observed_managed_encryption(monkeypatch) -> None:
    from app.settings import Settings
    from app.storage.migration import _preflight_object

    monkeypatch.setenv("ENVIRONMENT", "production")
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://unused",
        DB_ADMIN_URL="postgresql://unused",
        JWT_SECRET="x" * 32,
        STORAGE_BUCKET="private-files",
        STORAGE_SSE_ALGORITHM="aws:kms",
        STORAGE_SSE_KEY_ID="managed-key-id",
    )
    storage = FakeStorage()

    result = _preflight_object(storage, settings)

    assert result == {
        "put": True,
        "get": True,
        "metadata": True,
        "checksum": True,
        "delete": True,
        "encryption": False,
    }
    assert storage.objects == {}


def test_storage_metadata_columns_are_nullable_and_outbox_has_no_payload_fields() -> None:
    from app.db.models import (
        BugReportCommentAttachment,
        ExemptionRequestFile,
        GimelimAttachment,
        ImportSession,
        SoldierExemptionFile,
        StorageDeleteOutbox,
    )

    for model in (SoldierExemptionFile, ExemptionRequestFile, GimelimAttachment,
                  BugReportCommentAttachment, BugReport, ImportSession):
        for name in ("storage_key", "storage_sha256", "storage_size"):
            assert model.__table__.c[name].nullable
    assert set(StorageDeleteOutbox.__table__.columns.keys()) == {
        "id", "object_key", "created_at", "attempts", "last_error_code", "completed_at"
    }
    assert SoldierExemptionFile.__table__.c.data.nullable
    assert ImportSession.__table__.c.raw_excel.nullable
