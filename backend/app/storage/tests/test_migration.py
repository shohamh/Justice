from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import pytest

from app.settings import Settings
from app.storage.migration import run_migration
from app.storage.protocol import StoredObject

KEY = "gimelim/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
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
    session = ExistingReferenceSession([("gimelim", KEY, DIGEST, len(GOOD))])

    report = run_migration(session, storage, settings)

    assert report["cutover_ready"] is False
    assert report["existing_verified"] == 0
    assert report["errors"] == {"gimelim:existing_object_missing": 1}


def test_corrupt_preexisting_body_blocks_cutover_even_when_head_metadata_matches(
    migration_preflight,
) -> None:
    migration, settings = migration_preflight
    storage = ExistingObjectStorage(mode="corrupt")
    session = ExistingReferenceSession([("gimelim", KEY, DIGEST, len(GOOD))])

    report = run_migration(session, storage, settings)

    assert storage.reads == 1
    assert report["cutover_ready"] is False
    assert report["existing_verified"] == 0
    assert report["errors"] == {"gimelim:existing_object_hash_mismatch": 1}


def test_invalid_managed_prefix_blocks_cutover_readiness(migration_preflight) -> None:
    migration, settings = migration_preflight
    storage = ExistingObjectStorage(mode="good")
    session = ExistingReferenceSession(
        [("gimelim", "other/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", DIGEST, len(GOOD))]
    )

    report = run_migration(session, storage, settings)

    assert storage.reads == 0
    assert report["cutover_ready"] is False
    assert report["errors"] == {"gimelim:invalid_managed_key": 1}


def test_valid_preexisting_reference_is_byte_verified_before_cutover(migration_preflight) -> None:
    migration, settings = migration_preflight
    storage = ExistingObjectStorage(mode="good")
    session = ExistingReferenceSession([("gimelim", KEY, DIGEST, len(GOOD))])

    report = run_migration(session, storage, settings)

    assert storage.reads == 1
    assert report["existing_verified"] == 1
    assert report["errors"] == {}
    assert report["cutover_ready"] is True
