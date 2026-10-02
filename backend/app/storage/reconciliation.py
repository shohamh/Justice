"""Maintenance-only outbox processing and S3/Postgres consistency reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    BugReport,
    BugReportCommentAttachment,
    ExemptionRequestFile,
    GimelimAttachment,
    ImportSession,
    SoldierExemptionFile,
    StorageDeleteOutbox,
)
from app.storage.keys import MANAGED_PREFIXES
from app.storage.protocol import MaintenanceObjectStorage


@dataclass(slots=True)
class ReconciliationReport:
    orphan_keys: list[str] = field(default_factory=list)
    deleted_keys: list[str] = field(default_factory=list)
    missing_references: list[str] = field(default_factory=list)
    unknown_age_keys: list[str] = field(default_factory=list)
    outbox_completed: int = 0
    outbox_failed: int = 0
    orphan_delete_failed: int = 0


def _referenced_keys(session: Any) -> set[str]:
    if hasattr(session, "referenced_storage_keys"):
        return set(session.referenced_storage_keys())
    columns = [
        SoldierExemptionFile.storage_key,
        ExemptionRequestFile.storage_key,
        GimelimAttachment.storage_key,
        BugReportCommentAttachment.storage_key,
        BugReport.storage_key,
        BugReport.json_mirror_storage_key,
        ImportSession.storage_key,
    ]
    keys: set[str] = set()
    for column in columns:
        keys.update(key for key in session.scalars(select(column)) if key)
    return keys


def _iter_objects(storage: Any, prefix: str):
    if hasattr(storage, "iter_objects"):
        yield from storage.iter_objects(prefix=prefix)
    else:
        for key in storage.iter_keys(prefix=prefix):
            yield key, None


def reconcile_storage(
    session: Session,
    storage: MaintenanceObjectStorage,
    *,
    older_than_hours: int = 24,
    now: datetime | None = None,
    delete_orphans: bool = True,
    process_outbox: bool = True,
) -> ReconciliationReport:
    if older_than_hours < 1:
        raise ValueError("older_than_hours must be at least one")
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=older_than_hours)
    report = ReconciliationReport()
    referenced = _referenced_keys(session)

    for file_class in sorted(MANAGED_PREFIXES):
        prefix = f"{file_class}/"
        for key, last_modified in _iter_objects(storage, prefix):
            if key in referenced:
                continue
            report.orphan_keys.append(key)
            if last_modified is None:
                report.unknown_age_keys.append(key)
                continue
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=UTC)
            if last_modified <= cutoff and delete_orphans:
                try:
                    storage.delete(key=key)
                except Exception:
                    report.orphan_delete_failed += 1
                    continue
                report.deleted_keys.append(key)

    if not process_outbox:
        pending = []
    elif isinstance(session, Session):
        pending = session.scalars(
            select(StorageDeleteOutbox)
            .where(StorageDeleteOutbox.completed_at.is_(None))
            .where(StorageDeleteOutbox.created_at <= cutoff)
            .order_by(StorageDeleteOutbox.created_at)
        ).all()
    elif hasattr(session, "pending_delete_outbox"):
        pending = session.pending_delete_outbox()
    else:
        pending = []
    for item in pending:
        item.attempts += 1
        try:
            storage.delete(key=item.object_key)
            item.completed_at = now
            item.last_error_code = None
            report.outbox_completed += 1
        except Exception:
            item.last_error_code = "storage_delete_failed"
            report.outbox_failed += 1
    if pending:
        session.commit()

    if isinstance(session, Session):
        live = _referenced_keys(session)
        available = set()
        for file_class in sorted(MANAGED_PREFIXES):
            available.update(key for key, _ in _iter_objects(storage, f"{file_class}/"))
        report.missing_references.extend(sorted(live - available))
    return report
