from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest

from app.settings import Settings
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
        def __init__(self, existing): self.connection = Connection(existing); self.calls = []
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
