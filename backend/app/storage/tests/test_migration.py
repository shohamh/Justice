from __future__ import annotations

import json
import struct
import zlib
from hashlib import sha256
from io import BytesIO
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from sqlalchemy.orm import configure_mappers

from app.db.models import (
    BugReport,
    BugReportCommentAttachment,
    ExemptionRequestFile,
    GimelimAttachment,
    ImportSession,
    SoldierExemptionFile,
)
from app.settings import Settings, StorageMaintenanceSettings
from app.storage import backfill
from app.storage.migration import _existing_storage_references, run_migration
from app.storage.protocol import StoredObject

KEY = "gimelim/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
GOOD = b"verified object bytes"
DIGEST = sha256(GOOD).hexdigest()


class ExistingReferenceSession:
    def __init__(self, references):
        self.references = references

    def storage_references(self):
        return self.references


class ExistingObjectStorage:
    def __init__(self, *, mode: str):
        self.mode = mode
        self.reads = 0

    def put_bytes(self, *, key, data, content_type, sha256):
        return StoredObject(key, len(data), sha256, "aws:kms", "key-id")

    def open_read(self, *, key):
        self.reads += 1
        data = b"X" * len(GOOD) if self.mode == "corrupt" else GOOD
        return BytesIO(data), len(data)

    def head(self, *, key):
        if self.mode == "missing":
            return None
        # Simulate matching S3 metadata while the body itself has changed.
        return StoredObject(key, len(GOOD), DIGEST, "aws:kms", "key-id")

    def delete(self, *, key):
        pass

    def iter_keys(self, *, prefix):
        return iter(())


@pytest.fixture
def migration_preflight(monkeypatch):
    import app.storage.migration as migration

    empty_inventory = {
        "bug_report_json_mirror": {
            "rows": 0,
            "legacy_bytes": 0,
            "pending": 0,
            "reachable": 0,
            "unreachable": 0,
        }
    }
    monkeypatch.setattr(migration, "_inventory", lambda _: empty_inventory)
    monkeypatch.setattr(migration, "_record_payloads", lambda *_: iter(()))
    monkeypatch.setattr(
        migration,
        "_preflight_object",
        lambda *_: {
            "put": True,
            "get": True,
            "metadata": True,
            "checksum": True,
            "delete": True,
            "encryption": True,
        },
    )
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://unused",
        DB_ADMIN_URL="postgresql://unused",
        JWT_SECRET="x" * 32,
        STORAGE_BUCKET="private-files",
    )
    return migration, settings


def test_missing_preexisting_reference_blocks_cutover_readiness(migration_preflight) -> None:
    migration, settings = migration_preflight
    storage = ExistingObjectStorage(mode="missing")
    session = ExistingReferenceSession([("gimelim", OWNER_ID, KEY, DIGEST, len(GOOD))])

    report = run_migration(session, storage, settings)

    assert report["cutover_ready"] is False
    assert report["existing_verified"] == 0
    assert report["errors"] == {"gimelim:existing_object_missing": 1}


def test_corrupt_preexisting_body_blocks_cutover_even_when_head_metadata_matches(
    migration_preflight,
) -> None:
    migration, settings = migration_preflight
    storage = ExistingObjectStorage(mode="corrupt")
    session = ExistingReferenceSession([("gimelim", OWNER_ID, KEY, DIGEST, len(GOOD))])

    report = run_migration(session, storage, settings)

    assert storage.reads == 1
    assert report["cutover_ready"] is False
    assert report["existing_verified"] == 0
    assert report["errors"] == {"gimelim:existing_object_hash_mismatch": 1}


def test_invalid_managed_prefix_blocks_cutover_readiness(migration_preflight) -> None:
    migration, settings = migration_preflight
    storage = ExistingObjectStorage(mode="good")
    session = ExistingReferenceSession(
        [("gimelim", OWNER_ID, "other/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", DIGEST, len(GOOD))]
    )

    report = run_migration(session, storage, settings)

    assert storage.reads == 0
    assert report["cutover_ready"] is False
    assert report["errors"] == {"gimelim:invalid_managed_key": 1}


def test_valid_preexisting_reference_is_byte_verified_before_cutover(migration_preflight) -> None:
    migration, settings = migration_preflight
    storage = ExistingObjectStorage(mode="good")
    session = ExistingReferenceSession([("gimelim", OWNER_ID, KEY, DIGEST, len(GOOD))])

    report = run_migration(session, storage, settings)

    assert storage.reads == 1
    assert report["existing_verified"] == 1
    assert report["errors"] == {}
    assert report["cutover_ready"] is True


def test_same_class_object_from_another_row_blocks_cutover(migration_preflight) -> None:
    migration, settings = migration_preflight
    storage = ExistingObjectStorage(mode="good")
    other_object = "gimelim/cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    session = ExistingReferenceSession([("gimelim", OWNER_ID, other_object, DIGEST, len(GOOD))])

    report = run_migration(session, storage, settings)

    assert storage.reads == 0
    assert report["cutover_ready"] is False
    assert report["existing_verified"] == 0
    assert report["errors"] == {"gimelim:object_key_record_mismatch": 1}


def test_database_reference_enumerator_includes_owning_row_uuid() -> None:
    class QuerySession:
        def execute(self, statement):
            return [(OWNER_ID, KEY, DIGEST, len(GOOD))]

    reference = next(_existing_storage_references(QuerySession()))

    assert reference == ("soldier_exemption", OWNER_ID, KEY, DIGEST, len(GOOD))
def test_storage_metadata_migration_is_reversible_only_without_s3_references(monkeypatch):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "alembic/versions/4858092e72e7_add_object_storage_metadata.py"
    spec = importlib.util.spec_from_file_location("storage_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    class Result:
        def __init__(self, value): self.value = value
        def scalar_one(self): return self.value
    class Connection:
        def __init__(self, existing): self.existing = existing
        def execute(self, statement): return Result(bool(self.existing) and self.existing in str(statement))
    class Operations:
        def __init__(self, existing):
            self.connection = Connection(existing)
            self.calls = []
        def get_bind(self): return self.connection
        def __getattr__(self, name):
            return lambda *args, **kwargs: self.calls.append((name, args, kwargs))
    for reference in ("storage_key", "storage_delete_outbox"):
        operations = Operations(reference)
        monkeypatch.setattr(migration, "op", operations)
        with pytest.raises(RuntimeError, match="Cannot downgrade while storage objects"):
            migration.downgrade()
        assert operations.calls == []
    operations = Operations("")
    monkeypatch.setattr(migration, "op", operations)
    migration.downgrade()
    assert any(call[0] == "drop_table" and call[1][0] == "storage_delete_outbox" for call in operations.calls)
    assert any(call[0] == "alter_column" and call[2].get("nullable") is False for call in operations.calls)


def test_storage_outbox_grant_is_least_privilege():
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "alembic/versions/4858092e72e7_add_object_storage_metadata.py"
    source = path.read_text(encoding="utf-8")
    assert "REVOKE ALL ON TABLE storage_delete_outbox FROM app" in source
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE storage_delete_outbox TO app" in source


def _png_chunk(kind: bytes, value: bytes) -> bytes:
    return (
        struct.pack(">I", len(value))
        + kind
        + value
        + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)
    )


def _synthetic_png() -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30"))
        + _png_chunk(b"IEND", b"")
    )


class SyntheticMigrationSession:
    def __init__(self, records):
        self.records = records
        self.commits = 0
        self.rollbacks = 0
        self.expirations = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def expire_all(self):
        self.expirations += 1

    def storage_references(self):
        references = []
        for record in self.records:
            if record.storage_key:
                file_class = {
                    SoldierExemptionFile: "soldier_exemption",
                    ExemptionRequestFile: "exemption_request",
                    GimelimAttachment: "gimelim",
                    BugReportCommentAttachment: "bug_report_comment",
                    BugReport: "bug_report_screenshot",
                    ImportSession: "import_workbook",
                }[type(record)]
                references.append(
                    (
                        file_class,
                        record.id,
                        record.storage_key,
                        record.storage_sha256,
                        record.storage_size,
                    )
                )
            if isinstance(record, BugReport) and record.json_mirror_storage_key:
                references.append(
                    (
                        "bug_report_json_mirror",
                        record.id,
                        record.json_mirror_storage_key,
                        record.json_mirror_sha256,
                        None,
                    )
                )
        return references


class SyntheticMigrationStorage:
    def __init__(self, *, fail_once_key: str):
        self.objects = {}
        self.fail_once_key = fail_once_key
        self.failed_keys = set()
        self.put_attempts = {}

    def put_bytes(self, *, key, data, content_type, sha256):
        self.put_attempts[key] = self.put_attempts.get(key, 0) + 1
        if key == self.fail_once_key and key not in self.failed_keys:
            self.failed_keys.add(key)
            raise OSError("synthetic one-time storage interruption")
        stored = StoredObject(key, len(data), sha256, "aws:kms", "synthetic-key")
        self.objects[key] = (data, stored)
        return stored

    def open_read(self, *, key):
        data, _ = self.objects[key]
        return BytesIO(data), len(data)

    def head(self, *, key):
        item = self.objects.get(key)
        return item[1] if item else None

    def delete(self, *, key):
        self.objects.pop(key, None)

    def iter_keys(self, *, prefix):
        return iter(key for key in self.objects if key.startswith(prefix))


def _synthetic_record(model, **attributes):
    configure_mappers()
    record = model._sa_class_manager.new_instance()
    for name, value in attributes.items():
        setattr(record, name, value)
    return record


def test_synthetic_seven_class_migration_resumes_after_transient_storage_failure(
    monkeypatch, tmp_path
) -> None:
    """Exercise every legacy payload class and retry only the failed object."""
    import app.storage.migration as migration

    report_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    records = [
        _synthetic_record(
            SoldierExemptionFile,
            id=UUID("10000000-0000-4000-8000-000000000001"),
            data=b"%PDF-1.4\nsynthetic exemption\n%%EOF",
            content_type="application/pdf",
            storage_key=None,
            storage_sha256=None,
            storage_size=None,
        ),
        _synthetic_record(
            ExemptionRequestFile,
            id=UUID("10000000-0000-4000-8000-000000000002"),
            data=b"%PDF-1.4\nsynthetic request\n%%EOF",
            content_type="application/pdf",
            storage_key=None,
            storage_sha256=None,
            storage_size=None,
        ),
        _synthetic_record(
            GimelimAttachment,
            id=UUID("10000000-0000-4000-8000-000000000003"),
            data=b"%PDF-1.4\nsynthetic gimelim\n%%EOF",
            content_type="application/pdf",
            storage_key=None,
            storage_sha256=None,
            storage_size=None,
        ),
        _synthetic_record(
            BugReportCommentAttachment,
            id=UUID("10000000-0000-4000-8000-000000000004"),
            data=b"%PDF-1.4\nsynthetic comment\n%%EOF",
            content_type="application/pdf",
            storage_key=None,
            storage_sha256=None,
            storage_size=None,
        ),
        _synthetic_record(
            BugReport,
            id=report_id,
            screenshot=_synthetic_png(),
            json_file_path=None,
            storage_key=None,
            storage_sha256=None,
            storage_size=None,
            json_mirror_storage_key=None,
            json_mirror_sha256=None,
        ),
        _synthetic_record(
            ImportSession,
            id=UUID("10000000-0000-4000-8000-000000000006"),
            raw_excel=_synthetic_workbook(),
            storage_key=None,
            storage_sha256=None,
            storage_size=None,
        ),
    ]
    mirror = tmp_path / "bug_reports" / "synthetic.json"
    mirror.parent.mkdir()
    mirror.write_text(json.dumps({"kind": "synthetic", "id": str(report_id)}))
    records[4].json_file_path = str(mirror)
    monkeypatch.setattr(backfill, "LOG_DIR", tmp_path)

    session = SyntheticMigrationSession(records)
    failed_record = records[2]
    fail_key = "gimelim/" + str(failed_record.id)
    storage = SyntheticMigrationStorage(fail_once_key=fail_key)

    def inventory(_session):
        counts = {}
        classes = (
            ("soldier_exemption", SoldierExemptionFile, "data"),
            ("exemption_request", ExemptionRequestFile, "data"),
            ("gimelim", GimelimAttachment, "data"),
            ("bug_report_comment", BugReportCommentAttachment, "data"),
            ("bug_report_screenshot", BugReport, "screenshot"),
            ("import_workbook", ImportSession, "raw_excel"),
        )
        for label, model, payload_attr in classes:
            selected = [record for record in records if isinstance(record, model)]
            counts[label] = {
                "rows": len(selected),
                "legacy_bytes": sum(len(getattr(row, payload_attr) or b"") for row in selected),
                "pending": sum(row.storage_key is None for row in selected),
            }
        report = records[4]
        counts["bug_report_json_mirror"] = {
            "rows": 1,
            "legacy_bytes": mirror.stat().st_size,
            "pending": int(report.json_mirror_storage_key is None),
            "reachable": 1,
            "unreachable": 0,
        }
        return counts

    def record_payloads(_session, _batch_size):
        for record in records:
            if record.storage_key is None and getattr(
                record,
                "data",
                getattr(record, "screenshot", getattr(record, "raw_excel", None)),
            ) is not None:
                yield record, "main"
        if records[4].json_mirror_storage_key is None:
            yield records[4], "json_mirror"

    monkeypatch.setattr(migration, "_inventory", inventory)
    monkeypatch.setattr(migration, "_record_payloads", record_payloads)
    monkeypatch.setattr(
        migration,
        "_preflight_object",
        lambda *_: {name: True for name in ("put", "get", "metadata", "checksum", "delete", "encryption")},
    )
    monkeypatch.setattr(backfill, "object_session", lambda _record: session)
    settings = StorageMaintenanceSettings(
        _env_file=None,
        DATABASE_URL="postgresql://synthetic.invalid/storage-test",
        STORAGE_BUCKET="synthetic-private-files",
    )

    first = run_migration(session, storage, settings, batch_size=2)

    assert sum(item["pending"] for item in first["inventory"].values()) == 7
    assert first["migrated"] == 6
    assert first["failed"] == 1
    assert first["cutover_ready"] is False
    assert failed_record.storage_key is None
    assert session.commits == 6
    assert all(record.storage_key for record in records if record is not failed_record)
    assert records[4].json_mirror_storage_key is not None

    resumed = run_migration(session, storage, settings, batch_size=2)

    assert resumed["migrated"] == 1
    assert resumed["existing_verified"] == 7
    assert resumed["failed"] == 0
    assert all(item["pending"] == 0 for item in resumed["remaining"].values())
    assert resumed["cutover_ready"] is True
    assert session.commits == 7
    assert session.expirations >= 3
    assert storage.put_attempts[fail_key] == 2
    assert len(storage.objects) == 7


def _synthetic_workbook() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("xl/workbook.xml", "<workbook></workbook>")
    return buffer.getvalue()
