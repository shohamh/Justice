from __future__ import annotations

from io import BytesIO
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BugReport

_ACTIVE_STATUSES = ("open", "in_progress")
_VALID_SEVERITIES = ("low", "medium", "high")


def _select_bug_reports_for_export(
    session: Session,
    *,
    scope: Literal["all_active", "filtered"],
    severity: str | None,
    status: str | None,
) -> list[BugReport]:
    stmt = select(BugReport).where(BugReport.status.in_(_ACTIVE_STATUSES))

    if scope == "filtered":
        if severity in _VALID_SEVERITIES:
            stmt = stmt.where(BugReport.severity == severity)
        if status in _ACTIVE_STATUSES:
            stmt = stmt.where(BugReport.status == status)

    stmt = stmt.order_by(BugReport.created_at.desc(), BugReport.id.desc())
    return list(session.execute(stmt).scalars())


def _render_bug_report_export_zip(reports: list[BugReport]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("index.md", "")
    return buffer.getvalue()


def build_bug_report_export_zip(
    session: Session,
    *,
    scope: Literal["all_active", "filtered"],
    severity: str | None,
    status: str | None,
) -> bytes:
    reports = _select_bug_reports_for_export(
        session,
        scope=scope,
        severity=severity,
        status=status,
    )
    return _render_bug_report_export_zip(reports)
