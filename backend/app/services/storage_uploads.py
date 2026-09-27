from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import StorageDeleteOutbox
from app.storage.keys import FileClass, make_object_key
from app.storage.protocol import ObjectStorage, StoredObject

logger = logging.getLogger(__name__)


class StorageUploadError(RuntimeError):
    """Stable application error for an upload that could not be committed."""


def enqueue_storage_cleanup(session: Session, keys: Iterable[str]) -> None:
    """Best-effort durable cleanup request; deletion remains maintenance-only."""
    unique_keys = list(dict.fromkeys(keys))
    if not unique_keys:
        return
    try:
        session.rollback()
        for key in unique_keys:
            existing = session.scalar(select(StorageDeleteOutbox.id).where(StorageDeleteOutbox.object_key == key))
            if existing is None:
                session.add(StorageDeleteOutbox(object_key=key))
        session.commit()
    except Exception:
        session.rollback()
        logger.error("storage_upload_cleanup_enqueue_failed", extra={"object_count": len(unique_keys)})



def put_managed_object(storage: ObjectStorage, *, key: str, data: bytes, content_type: str) -> StoredObject:
    checksum = hashlib.sha256(data).hexdigest()
    stored = storage.put_bytes(key=key, data=data, content_type=content_type, sha256=checksum)
    if stored.key != key or stored.size != len(data) or stored.sha256 != checksum:
        raise StorageUploadError("storage_metadata_mismatch")
    return stored


class StorageReadError(RuntimeError):
    """A referenced object was unavailable or failed its metadata check."""


def read_uploaded_object(storage: ObjectStorage, record: Any, *, file_class: FileClass, legacy_field: str, max_bytes: int) -> bytes:
    key = getattr(record, "storage_key", None)
    if not key:
        legacy = getattr(record, legacy_field, None)
        if legacy is None:
            raise FileNotFoundError("file_not_found")
        return legacy
    expected_key = make_object_key(file_class, record.id)
    if key != expected_key:
        raise StorageReadError("storage_integrity_failed")
    try:
        body, reported_size = storage.open_read(key=key)
        chunks: list[bytes] = []
        digest = hashlib.sha256()
        size = 0
        while chunk := body.read(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise StorageReadError("storage_integrity_failed")
            digest.update(chunk)
            chunks.append(chunk)
        content = b"".join(chunks)
    except StorageReadError:
        raise
    except Exception as exc:
        raise StorageReadError("storage_unavailable") from exc
    finally:
        close = getattr(locals().get("body"), "close", None)
        if close:
            close()
    if size != reported_size or size != record.storage_size or digest.hexdigest() != record.storage_sha256:
        raise StorageReadError("storage_integrity_failed")
    return content

def persist_uploaded_object(
    session: Session,
    storage: ObjectStorage,
    record: Any,
    *,
    file_class: FileClass,
    data: bytes,
    content_type: str,
) -> str:
    """Put an object first, then bind its verified metadata to a pending row."""
    session.add(record)
    session.flush()
    key = make_object_key(file_class, record.id)
    checksum = hashlib.sha256(data).hexdigest()
    try:
        stored = storage.put_bytes(key=key, data=data, content_type=content_type, sha256=checksum)
        if stored.key != key or stored.size != len(data) or stored.sha256 != checksum:
            raise StorageUploadError("storage_metadata_mismatch")
        record.storage_key = stored.key
        record.storage_sha256 = stored.sha256
        record.storage_size = stored.size
        # Never keep a second durable database copy after object persistence.
        if hasattr(record, "data"):
            record.data = None
        if hasattr(record, "screenshot"):
            record.screenshot = None
        if hasattr(record, "raw_excel"):
            record.raw_excel = None
        session.flush()
    except Exception as exc:
        enqueue_storage_cleanup(session, [key])
        if isinstance(exc, StorageUploadError):
            raise
        raise StorageUploadError("storage_write_failed") from exc
    return key


def commit_uploaded_objects(session: Session, keys: Iterable[str]) -> None:
    """Commit metadata or queue every uploaded object for maintenance deletion."""
    keys = list(keys)
    try:
        session.commit()
    except Exception as exc:
        enqueue_storage_cleanup(session, keys)
        raise StorageUploadError("upload_persistence_failed") from exc
