from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed, require_roles
from app.db.models import BugReport, Soldier
from app.db.session import get_session
from app.services import bug_reports as svc

router = APIRouter(tags=["bug_reports"])

_MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class NavHistoryEntry(BaseModel):
    path: str
    timestamp: str


class BugReportSubmitBody(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    severity: Literal["low", "medium", "high"]
    screenshot: str | None = None
    route: str
    nav_history: list[NavHistoryEntry] = Field(default_factory=list)


def _decode_screenshot(b64: str) -> bytes | None:
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    if len(data) > _MAX_SCREENSHOT_BYTES or not data.startswith(_PNG_MAGIC):
        return None
    return data


@router.post("/bug-reports", status_code=status.HTTP_201_CREATED)
def submit_bug_report(
    body: BugReportSubmitBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    screenshot_bytes = _decode_screenshot(body.screenshot) if body.screenshot else None
    try:
        svc.write_bug_report(
            session,
            reporter=user,
            description=body.description,
            severity=body.severity,
            screenshot=screenshot_bytes,
            route=body.route,
            nav_history=[entry.model_dump() for entry in body.nav_history],
        )
    except svc.BugReportWriteError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="bug_report_write_failed") from exc
    session.commit()
    return {"status": "ok"}


class BugReportSummaryOut(BaseModel):
    id: uuid.UUID
    reporter_id: uuid.UUID
    description: str
    severity: str
    status: str
    route: str
    nav_history: list[dict] | None
    audit_snapshot: list[dict] | None
    user_snapshot: dict | None
    has_screenshot: bool
    created_at: datetime
    updated_at: datetime


class PaginatedBugReports(BaseModel):
    items: list[BugReportSummaryOut]
    total: int


class UpdateBugReportStatusBody(BaseModel):
    status: Literal["open", "in_progress", "resolved"]


def _summary_out(report: BugReport) -> BugReportSummaryOut:
    return BugReportSummaryOut(
        id=report.id,
        reporter_id=report.reporter_id,
        description=report.description,
        severity=report.severity,
        status=report.status,
        route=report.route,
        nav_history=report.nav_history,
        audit_snapshot=report.audit_snapshot,
        user_snapshot=report.user_snapshot,
        has_screenshot=report.screenshot is not None,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.get("/admin/bug-reports", response_model=PaginatedBugReports)
def list_bug_reports(
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
    severity: Literal["low", "medium", "high"] | None = None,
    status_filter: Literal["open", "in_progress", "resolved"] | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedBugReports:
    query = select(BugReport)
    count_query = select(func.count()).select_from(BugReport)
    if severity is not None:
        query = query.where(BugReport.severity == severity)
        count_query = count_query.where(BugReport.severity == severity)
    if status_filter is not None:
        query = query.where(BugReport.status == status_filter)
        count_query = count_query.where(BugReport.status == status_filter)

    total = session.execute(count_query).scalar_one()
    items = session.execute(
        query.order_by(BugReport.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return PaginatedBugReports(items=[_summary_out(r) for r in items], total=total)


@router.get("/admin/bug-reports/{report_id}/json")
def get_bug_report_json(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
) -> Response:
    report = session.get(BugReport, report_id)
    if report is None or not report.json_file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bug_report_json_not_found")
    path = Path(report.json_file_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bug_report_json_not_found")
    return Response(content=path.read_text(), media_type="application/json")


@router.get("/admin/bug-reports/{report_id}/screenshot")
def get_bug_report_screenshot(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
) -> Response:
    report = session.get(BugReport, report_id)
    if report is None or report.screenshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bug_report_screenshot_not_found")
    return Response(content=report.screenshot, media_type="image/png")


@router.patch("/admin/bug-reports/{report_id}", response_model=BugReportSummaryOut)
def update_bug_report_status(
    report_id: uuid.UUID,
    body: UpdateBugReportStatusBody,
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
) -> BugReportSummaryOut:
    report = session.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bug_report_not_found")
    report.status = body.status
    report.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(report)
    return _summary_out(report)
