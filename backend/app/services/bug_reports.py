from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, BugReport, Soldier
from app.logging_config import LOG_DIR

logger = logging.getLogger(__name__)


class BugReportWriteError(Exception):
    """Raised only when both the JSON mirror and the DB insert fail."""


class BugReportImportError(Exception):
    """Raised for a single file when importing a JSON-mirrored bug report fails."""


@dataclass
class BugReportWriteResult:
    persisted_to_db: bool
    json_file_path: str | None


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
) -> BugReportWriteResult:
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
    json_file_path = _write_json_mirror(report_id, created_at, json_payload)

    persisted_to_db = True
    try:
        report = BugReport(
            reporter_id=reporter.id,
            description=description,
            severity=severity,
            route=route,
            screenshot=screenshot,
            nav_history=nav_history,
            audit_snapshot=audit_snapshot,
            user_snapshot=user_snapshot,
            json_file_path=json_file_path,
        )
        report.id = report_id
        session.add(report)
        session.flush()
    except Exception:
        session.rollback()
        logger.exception("bug_report_db_insert_failed", extra={"report_id": str(report_id)})
        persisted_to_db = False

    if not persisted_to_db and json_file_path is None:
        raise BugReportWriteError("both_json_and_db_write_failed")

    return BugReportWriteResult(persisted_to_db=persisted_to_db, json_file_path=json_file_path)


_REQUIRED_IMPORT_FIELDS = ("id", "reporter_id", "description", "severity", "route", "created_at")


def import_bug_report_json(session: Session, payload: dict[str, Any]) -> uuid.UUID:
    """Insert one bug report from a previously-written JSON mirror payload
    (the same shape `write_bug_report` produces — see `_write_json_mirror`).

    Used to recover reports that only ever reached disk because the DB insert
    failed at submission time (e.g. during a DB outage). Raises
    BugReportImportError if the payload is malformed, the report already
    exists in the DB, or the insert itself fails (e.g. the reporter no longer
    exists). Runs in a SAVEPOINT so a failure here does not roll back other
    reports already imported in the same request.
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

    if session.get(BugReport, report_id) is not None:
        raise BugReportImportError("already_exists")

    try:
        with session.begin_nested():
            report = BugReport(
                reporter_id=reporter_id,
                description=str(payload["description"])[:2000],
                severity=payload["severity"],
                route=str(payload["route"])[:500],
                screenshot=None,
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
