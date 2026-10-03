"""Inventory, preflight, and bounded resumable legacy-file migration."""

from __future__ import annotations

import os
import re
from collections import Counter
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    BugReport,
    BugReportCommentAttachment,
    ExemptionRequestFile,
    GimelimAttachment,
    ImportSession,
    SoldierExemptionFile,
)
from app.settings import StorageMaintenanceSettings
from app.storage.backfill import (
    MAX_LEGACY_BYTES,
    BackfillError,
    BackfillResult,
    backfill_record,
    validate_legacy_record,
)
from app.storage.keys import make_object_key, validate_managed_key
from app.storage.protocol import MaintenanceObjectStorage

FILE_MODELS = (
    ("soldier_exemption", SoldierExemptionFile, "data"),
    ("exemption_request", ExemptionRequestFile, "data"),
    ("gimelim", GimelimAttachment, "data"),
    ("bug_report_comment", BugReportCommentAttachment, "data"),
    ("bug_report_screenshot", BugReport, "screenshot"),
    ("import_workbook", ImportSession, "raw_excel"),
)


def _inventory(session: Session) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for label, model, payload_column in FILE_MODELS:
        column = getattr(model, payload_column)
        count, size, pending = session.execute(
            select(
                func.count(model.id),
                func.coalesce(func.sum(func.length(column)), 0),
                func.count(model.id).filter(model.storage_key.is_(None), column.is_not(None)),
            )
        ).one()
        result[label] = {"rows": int(count), "legacy_bytes": int(size), "pending": int(pending)}
    paths = session.scalars(
        select(BugReport.json_file_path).where(
            BugReport.json_file_path.is_not(None), BugReport.json_mirror_storage_key.is_(None)
        )
    ).all()
    reachable = missing = path_bytes = 0
    for raw_path in paths:
        try:
            path = Path(raw_path)
            path_bytes += path.stat().st_size
            reachable += 1
        except OSError:
            missing += 1
    result["bug_report_json_mirror"] = {
        "rows": len(paths),
        "legacy_bytes": path_bytes,
        "pending": len(paths),
        "reachable": reachable,
        "unreachable": missing,
    }
    return result


def _preflight_object(
    storage: MaintenanceObjectStorage, settings: StorageMaintenanceSettings
) -> dict[str, bool]:
    data = b"justice-storage-preflight"
    digest = sha256(data).hexdigest()
    key = make_object_key("import_workbook", uuid4())
    result = {
        "put": False,
        "get": False,
        "metadata": False,
        "checksum": False,
        "delete": False,
        "encryption": False,
    }
    uploaded = False
    try:
        written = storage.put_bytes(
            key=key, data=data, content_type="application/octet-stream", sha256=digest
        )
        uploaded = result["put"] = True
        body, length = storage.open_read(key=key)
        try:
            readback = body.read(len(data) + 1)
        finally:
            body.close()
        result["get"] = length == len(data) and readback == data
        head = storage.head(key=key)
        result["metadata"] = head is not None
        result["checksum"] = bool(
            head
            and written.sha256 == digest
            and head.sha256 == digest
            and written.size == len(data)
            and head.size == len(data)
        )
        production = os.getenv("ENVIRONMENT", "development").lower() == "production"
        result["encryption"] = not production or (
            bool(settings.storage_sse_algorithm)
            and bool(settings.storage_sse_key_id)
            and written.encryption_algorithm == settings.storage_sse_algorithm
            and written.encryption_key_id == settings.storage_sse_key_id
            and head is not None
            and head.encryption_algorithm == settings.storage_sse_algorithm
            and head.encryption_key_id == settings.storage_sse_key_id
        )
    except Exception:
        pass
    finally:
        if uploaded:
            try:
                storage.delete(key=key)
                result["delete"] = True
            except Exception:
                pass
    return result


def _record_payloads(session: Session, batch_size: int):
    for _, model, payload_column in FILE_MODELS:
        key_col = model.storage_key
        data_col = getattr(model, payload_column)
        attempted: set[Any] = set()
        while True:
            stmt = (
                select(model)
                .where(key_col.is_(None), data_col.is_not(None))
                .order_by(model.id)
                .limit(batch_size)
            )
            if attempted:
                stmt = stmt.where(model.id.not_in(attempted))
            batch = session.scalars(stmt).all()
            if not batch:
                break
            yield from ((record, "main") for record in batch)
            attempted.update(record.id for record in batch)
            if len(batch) < batch_size:
                break
    attempted: set[Any] = set()
    while True:
        stmt = (
            select(BugReport)
            .where(
                BugReport.json_file_path.is_not(None), BugReport.json_mirror_storage_key.is_(None)
            )
            .order_by(BugReport.id)
            .limit(batch_size)
        )
        if attempted:
            stmt = stmt.where(BugReport.id.not_in(attempted))
        batch = session.scalars(stmt).all()
        if not batch:
            break
        yield from ((report, "json_mirror") for report in batch)
        attempted.update(report.id for report in batch)
        if len(batch) < batch_size:
            break


def _existing_storage_references(session: Session):
    """Yield class, owning row UUID, key, recorded digest, and size for every object ref."""
    if hasattr(session, "storage_references"):
        yield from session.storage_references()
        return
    model_columns = (
        (
            "soldier_exemption",
            SoldierExemptionFile,
            "storage_key",
            "storage_sha256",
            "storage_size",
        ),
        (
            "exemption_request",
            ExemptionRequestFile,
            "storage_key",
            "storage_sha256",
            "storage_size",
        ),
        ("gimelim", GimelimAttachment, "storage_key", "storage_sha256", "storage_size"),
        (
            "bug_report_comment",
            BugReportCommentAttachment,
            "storage_key",
            "storage_sha256",
            "storage_size",
        ),
        ("bug_report_screenshot", BugReport, "storage_key", "storage_sha256", "storage_size"),
        (
            "bug_report_json_mirror",
            BugReport,
            "json_mirror_storage_key",
            "json_mirror_sha256",
            None,
        ),
        ("import_workbook", ImportSession, "storage_key", "storage_sha256", "storage_size"),
    )
    for file_class, model, key_name, hash_name, size_name in model_columns:
        key_column = getattr(model, key_name)
        selected = [model.id, key_column, getattr(model, hash_name)]
        if size_name:
            selected.append(getattr(model, size_name))
        stmt = select(*selected).where(key_column.is_not(None)).execution_options(yield_per=256)
        for row in session.execute(stmt):
            yield file_class, row[0], row[1], row[2], row[3] if size_name else None


def _verify_existing_objects(
    session: Session, storage: MaintenanceObjectStorage
) -> tuple[int, Counter[tuple[str, str]]]:
    """Verify key namespace, S3 HEAD metadata, and streamed object bytes for every reference."""
    verified = 0
    failures: Counter[tuple[str, str]] = Counter()
    for (
        file_class,
        row_id,
        object_key,
        expected_hash,
        expected_size,
    ) in _existing_storage_references(session):
        if not validate_managed_key(object_key) or not object_key.startswith(f"{file_class}/"):
            failures[(file_class, "invalid_managed_key")] += 1
            continue
        try:
            expected_key = make_object_key(file_class, row_id)
        except (TypeError, ValueError):
            expected_key = None
        if object_key != expected_key:
            failures[(file_class, "object_key_record_mismatch")] += 1
            continue
        if (
            not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
        ):
            failures[(file_class, "missing_storage_hash")] += 1
            continue
        try:
            metadata = storage.head(key=object_key)
        except Exception:
            failures[(file_class, "existing_object_unavailable")] += 1
            continue
        if metadata is None:
            failures[(file_class, "existing_object_missing")] += 1
            continue
        if metadata.key != object_key or metadata.sha256 != expected_hash:
            failures[(file_class, "existing_object_metadata_mismatch")] += 1
            continue
        if expected_size is not None and metadata.size != expected_size:
            failures[(file_class, "existing_object_size_mismatch")] += 1
            continue
        if metadata.size < 0 or metadata.size > MAX_LEGACY_BYTES:
            failures[(file_class, "existing_object_size_mismatch")] += 1
            continue
        try:
            body, content_length = storage.open_read(key=object_key)
            digest = sha256()
            actual_size = 0
            try:
                while True:
                    chunk = body.read(min(64 * 1024, MAX_LEGACY_BYTES + 1 - actual_size))
                    if not chunk:
                        break
                    digest.update(chunk)
                    actual_size += len(chunk)
                    if actual_size > MAX_LEGACY_BYTES:
                        break
            finally:
                body.close()
        except Exception:
            failures[(file_class, "existing_object_read_failed")] += 1
            continue
        if (
            content_length != metadata.size
            or actual_size != metadata.size
            or (expected_size is not None and actual_size != expected_size)
        ):
            failures[(file_class, "existing_object_size_mismatch")] += 1
            continue
        if digest.hexdigest() != expected_hash:
            failures[(file_class, "existing_object_hash_mismatch")] += 1
            continue
        verified += 1
    return verified, failures


def run_migration(
    session: Session,
    storage: MaintenanceObjectStorage,
    settings: StorageMaintenanceSettings,
    *,
    dry_run: bool = False,
    batch_size: int = 100,
) -> dict[str, Any]:
    if not 1 <= batch_size <= 5000:
        raise ValueError("batch_size must be between 1 and 5000")
    inventory = _inventory(session)
    storage_check = _preflight_object(storage, settings)
    errors: Counter[tuple[str, str]] = Counter()
    migrated = 0
    validated = 0
    if dry_run:
        for record, payload in _record_payloads(session, batch_size):
            try:
                validate_legacy_record(record, payload=payload)
                validated += 1
            except BackfillError as exc:
                label = (
                    "bug_report_json_mirror" if payload == "json_mirror" else type(record).__name__
                )
                errors[(label, exc.error_code)] += 1
    else:
        for record, payload in _record_payloads(session, batch_size):
            try:
                result: BackfillResult = backfill_record(storage, record, payload=payload)
                if result.status == "migrated":
                    migrated += 1
            except BackfillError as exc:
                label = (
                    "bug_report_json_mirror" if payload == "json_mirror" else type(record).__name__
                )
                errors[(label, exc.error_code)] += 1
            # Each record is committed independently for safe restart. batch_size
            # bounds the session identity map and caps each selection chunk.
            if migrated and migrated % batch_size == 0:
                session.expire_all()
    existing_verified, reference_errors = _verify_existing_objects(session, storage)
    errors.update(reference_errors)
    failed = sum(errors.values())
    final_inventory = _inventory(session)
    cutover_ready = (
        (not dry_run)
        and failed == 0
        and all(storage_check.values())
        and all(item.get("pending", 0) == 0 for item in final_inventory.values())
        and final_inventory["bug_report_json_mirror"].get("unreachable", 0) == 0
    )
    return {
        "dry_run": dry_run,
        "inventory": inventory,
        "remaining": final_inventory,
        "storage_check": storage_check,
        "validated": validated,
        "migrated": migrated,
        "existing_verified": existing_verified,
        "failed": failed,
        "errors": {f"{label}:{code}": count for (label, code), count in sorted(errors.items())},
        "cutover_ready": cutover_ready,
    }


def write_restricted_report(path: str | Path, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(target.parent, 0o700)
    target.write_text(__import__("json").dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    with suppress(OSError):
        os.chmod(target, 0o600)
