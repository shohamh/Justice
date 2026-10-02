from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, BugReport, Soldier
from app.logging_config import LOG_DIR
from app.services.storage_uploads import (
    enqueue_storage_cleanup,
    put_managed_object,
)
from app.storage.keys import make_object_key
from app.storage.protocol import ObjectStorage

logger = logging.getLogger(__name__)

_DAILY_BUG_REPORT_LIMIT = 50


class BugReportWriteError(Exception):
    """Raised only when both the JSON mirror and the DB insert fail."""


class BugReportRateLimitError(Exception):
    """Raised when a reporter exceeds the daily bug-report submission cap."""


class BugReportImportError(Exception):
    """Raised for a single file when importing a JSON-mirrored bug report fails."""


@dataclass
class BugReportWriteResult:
    persisted_to_db: bool
    json_file_path: str | None
    storage_keys: list[str]


def _json_default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {value!r}")


def _audit_snapshot(session: Session, reporter_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        select(AuditLog)
        .where(AuditLog.actor_id == reporter_id)
        .order_by(AuditLog.created_at.desc())
        .limit(20)
    ).scalars().all()
    return [
        {
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id) if row.entity_id else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _write_json_mirror(report_id: uuid.UUID, created_at: datetime, payload: dict[str, Any]) -> str | None:
    json_dir = LOG_DIR / "bug_reports"
    try:
        json_dir.mkdir(parents=True, exist_ok=True)
        file_path = json_dir / f"{report_id}_{created_at.strftime('%Y%m%dT%H%M%S')}.json"
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        return str(file_path)
    except (OSError, UnicodeError):
        logger.exception("bug_report_json_write_failed", extra={"report_id": str(report_id)})
        return None


def write_bug_report(
    session: Session,
    *,
    reporter: Soldier,
    description: str,
    severity: str,
    screenshot: bytes | None,
    route: str,
    nav_history: list[dict[str, Any]],
    storage: ObjectStorage | None = None,
) -> BugReportWriteResult:
    window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_count = session.execute(
        select(func.count()).select_from(BugReport).where(
            BugReport.reporter_id == reporter.id,
            BugReport.created_at >= window_start,
        )
    ).scalar_one()
    if recent_count >= _DAILY_BUG_REPORT_LIMIT:
        raise BugReportRateLimitError("daily_bug_report_limit_exceeded")

    report_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)

    audit_snapshot = _audit_snapshot(session, reporter.id)
    user_snapshot = {
        "id": str(reporter.id),
        "full_name": reporter.full_name,
        "rank": reporter.rank,
        "role": reporter.role,
        "personal_number": reporter.personal_number,
    }

    json_payload = {
        "id": str(report_id),
        "reporter_id": str(reporter.id),
        "description": description,
        "severity": severity,
        "route": route,
        "nav_history": nav_history,
        "audit_snapshot": audit_snapshot,
        "user_snapshot": user_snapshot,
        "has_screenshot": screenshot is not None,
        "created_at": created_at.isoformat(),
    }
    json_file_path = _write_json_mirror(report_id, created_at, json_payload) if storage is None else None
    storage_keys: list[str] = []
    screenshot_stored = None
    mirror_stored = None
    if storage is not None:
        try:
            if screenshot is not None:
                screenshot_key = make_object_key("bug_report_screenshot", report_id)
                storage_keys.append(screenshot_key)
                screenshot_stored = put_managed_object(storage, key=screenshot_key, data=screenshot, content_type="image/png")
            mirror_key = make_object_key("bug_report_json_mirror", report_id)
            json_payload.update({
                "json_mirror_storage_key": mirror_key,
                "screenshot_storage_key": screenshot_stored.key if screenshot_stored else None,
                "screenshot_storage_sha256": screenshot_stored.sha256 if screenshot_stored else None,
                "screenshot_storage_size": screenshot_stored.size if screenshot_stored else None,
            })
            mirror_data = json.dumps(json_payload, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")
            storage_keys.append(mirror_key)
            mirror_stored = put_managed_object(storage, key=mirror_key, data=mirror_data, content_type="application/json")
        except Exception as exc:
            enqueue_storage_cleanup(session, storage_keys)
            logger.error("bug_report_object_write_failed", extra={"report_id": str(report_id), "object_count": len(storage_keys)})
            raise BugReportWriteError("bug_report_object_write_failed") from exc

    persisted_to_db = True
    try:
        report = BugReport(
            reporter_id=reporter.id,
            description=description,
            severity=severity,
            route=route,
            screenshot=screenshot if storage is None else None,
            storage_key=screenshot_stored.key if screenshot_stored else None,
            storage_sha256=screenshot_stored.sha256 if screenshot_stored else None,
            storage_size=screenshot_stored.size if screenshot_stored else None,
            json_mirror_storage_key=mirror_stored.key if mirror_stored else None,
            json_mirror_sha256=mirror_stored.sha256 if mirror_stored else None,
            nav_history=nav_history,
            audit_snapshot=audit_snapshot,
            user_snapshot=user_snapshot,
            json_file_path=json_file_path,
        )
        report.id = report_id
        session.add(report)
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("bug_report_db_insert_failed", extra={"report_id": str(report_id)})
        persisted_to_db = False

    if not persisted_to_db and json_file_path is None:
        raise BugReportWriteError("both_json_and_db_write_failed")

    return BugReportWriteResult(persisted_to_db=persisted_to_db, json_file_path=json_file_path, storage_keys=storage_keys)


_REQUIRED_IMPORT_FIELDS = ("id", "reporter_id", "description", "severity", "route", "created_at")


def import_bug_report_json(
    session: Session, payload: dict[str, Any], *, mirror_sha256: str | None = None,
    mirror_size: int | None = None,
) -> uuid.UUID:
    """Insert one bug report from a previously-written JSON mirror payload
    (the same shape `write_bug_report` produces — see `_write_json_mirror`).

    Used to recover reports that only ever reached disk because the DB insert
    failed at submission time (e.g. during a DB outage), or to move reports
    between environments (e.g. staging to prod) where the original reporter's
    soldier row doesn't exist. If `reporter_id` doesn't resolve to a soldier
    in this DB, the report is imported anyway with reporter_id=None — the
    original reporter's details already live in `user_snapshot`, captured at
    submission time. Raises BugReportImportError if the payload is malformed,
    the report already exists in the DB, or the insert itself fails for some
    other reason. Runs in a SAVEPOINT so a failure here does not roll back
    other reports already imported in the same request.
    """
    missing = [f for f in _REQUIRED_IMPORT_FIELDS if not payload.get(f)]
    if missing:
        raise BugReportImportError(f"missing_fields:{','.join(missing)}")
    try:
        report_id = uuid.UUID(str(payload["id"]))
        reporter_id = uuid.UUID(str(payload["reporter_id"]))
        created_at = datetime.fromisoformat(payload["created_at"])
    except (ValueError, TypeError) as exc:
        raise BugReportImportError("malformed_fields") from exc
    if payload["severity"] not in ("low", "medium", "high"):
        raise BugReportImportError("invalid_severity")
    mirror_key = payload.get("json_mirror_storage_key")
    if mirror_key is not None and mirror_key != make_object_key("bug_report_json_mirror", report_id):
        raise BugReportImportError("invalid_mirror_key")
    screenshot_key = payload.get("screenshot_storage_key")
    if screenshot_key is not None and screenshot_key != make_object_key("bug_report_screenshot", report_id):
        raise BugReportImportError("invalid_screenshot_key")
    if bool(payload.get("has_screenshot")) != (screenshot_key is not None):
        raise BugReportImportError("invalid_screenshot_reference")

    if session.get(BugReport, report_id) is not None:
        raise BugReportImportError("already_exists")

    if session.get(Soldier, reporter_id) is None:
        reporter_id = None

    try:
        with session.begin_nested():
            report = BugReport(
                reporter_id=reporter_id,
                description=str(payload["description"])[:2000],
                severity=payload["severity"],
                route=str(payload["route"])[:500],
                screenshot=None,
                storage_key=payload.get("screenshot_storage_key"),
                storage_sha256=payload.get("screenshot_storage_sha256"),
                storage_size=payload.get("screenshot_storage_size"),
                json_mirror_storage_key=payload.get("json_mirror_storage_key"),
                json_mirror_sha256=mirror_sha256,
                nav_history=payload.get("nav_history") or None,
                audit_snapshot=payload.get("audit_snapshot") or None,
                user_snapshot=payload.get("user_snapshot") or None,
                json_file_path=None,
            )
            report.id = report_id
            report.created_at = created_at
            session.add(report)
            session.flush()
    except Exception as exc:
        raise BugReportImportError("insert_failed") from exc
    return report_id
