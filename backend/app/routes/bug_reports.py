from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed, require_roles
from app.db.models import (
    BugReport,
    BugReportComment,
    BugReportCommentAttachment,
    NotificationType,
    Soldier,
)
from app.db.session import get_session
from app.services import bug_reports as svc
from app.services.notifications import create_notification

router = APIRouter(tags=["bug_reports"])

_MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_IMPORT_FILES = 50
_MAX_IMPORT_FILE_BYTES = 1 * 1024 * 1024  # 1 MB — JSON mirror files are lightweight text

# Comment attachments: same magic-byte-validation convention as
# exemption_requests.py's module-private `_magic_bytes_match` — that helper
# isn't exported/imported cross-module anywhere in this codebase (checked:
# approvals_export.py also touches ExemptionRequestFile but does not import
# it), so per that established convention this is a small local duplicate,
# not a shared import.
_COMMENT_ATTACHMENT_MAGIC: dict[str, list[bytes]] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/gif": [b"GIF87a", b"GIF89a"],
}
_ALLOWED_COMMENT_ATTACHMENT_TYPES = set(_COMMENT_ATTACHMENT_MAGIC)
_MAX_COMMENT_ATTACHMENT_BYTES = 5 * 1024 * 1024  # 5 MB, matching the bug report's own screenshot cap

# Count caps to bound unbounded growth on a single report/comment. No existing
# product-defined cap for either was found elsewhere in the codebase; these are
# reasonable defaults. 400 (not 429) matches this file's own `too_many_files`
# precedent (see import_bug_reports below) and swaps.py's `too_many_targets` —
# 429 in this codebase is reserved for time-based rate limiting (auth.py login
# attempts, this file's own submit_bug_report, notifications.py), not count caps.
MAX_COMMENTS_PER_REPORT = 200
MAX_ATTACHMENTS_PER_COMMENT = 10


def _comment_attachment_magic_bytes_match(content_type: str, data: bytes) -> bool:
    return any(data[: len(prefix)] == prefix for prefix in _COMMENT_ATTACHMENT_MAGIC.get(content_type, []))


class NavHistoryEntry(BaseModel):
    path: str = Field(max_length=500)
    timestamp: str = Field(max_length=64)


class BugReportSubmitBody(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    severity: Literal["low", "medium", "high"]
    screenshot: str | None = Field(default=None, max_length=7 * 1024 * 1024)
    route: str = Field(max_length=500)
    nav_history: list[NavHistoryEntry] = Field(default_factory=list, max_length=15)


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
    except svc.BugReportRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
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
    comment_count: int
    last_comment_at: datetime | None
    has_unseen_activity: bool


class PaginatedBugReports(BaseModel):
    items: list[BugReportSummaryOut]
    total: int


class UpdateBugReportStatusBody(BaseModel):
    status: Literal["open", "in_progress", "resolved", "wont_fix"]


def _summary_out(
    report: BugReport,
    *,
    comment_count: int,
    last_comment_at: datetime | None,
    has_unseen_activity: bool = False,
) -> BugReportSummaryOut:
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
        comment_count=comment_count,
        last_comment_at=last_comment_at,
        has_unseen_activity=has_unseen_activity,
    )


def _comment_aggregates_subquery():
    return (
        select(
            BugReportComment.bug_report_id.label("bug_report_id"),
            func.count(BugReportComment.id).label("comment_count"),
            func.max(BugReportComment.created_at).label("last_comment_at"),
        )
        .group_by(BugReportComment.bug_report_id)
        .subquery()
    )


def _summary_with_comment_aggregates(session: Session, report: BugReport) -> BugReportSummaryOut:
    comment_count, last_comment_at = session.execute(
        select(
            func.count(BugReportComment.id),
            func.max(BugReportComment.created_at),
        ).where(BugReportComment.bug_report_id == report.id)
    ).one()
    return _summary_out(
        report,
        comment_count=comment_count,
        last_comment_at=last_comment_at,
    )


@router.get("/admin/bug-reports", response_model=PaginatedBugReports)
def list_bug_reports(
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
    severity: Literal["low", "medium", "high"] | None = None,
    status_filter: Literal["open", "in_progress", "resolved", "wont_fix"] | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> PaginatedBugReports:
    comment_aggregates = _comment_aggregates_subquery()
    query = (
        select(
            BugReport,
            func.coalesce(comment_aggregates.c.comment_count, 0).label("comment_count"),
            comment_aggregates.c.last_comment_at,
        )
        .outerjoin(comment_aggregates, comment_aggregates.c.bug_report_id == BugReport.id)
    )
    count_query = select(func.count()).select_from(BugReport)
    if severity is not None:
        query = query.where(BugReport.severity == severity)
        count_query = count_query.where(BugReport.severity == severity)
    if status_filter is not None:
        query = query.where(BugReport.status == status_filter)
        count_query = count_query.where(BugReport.status == status_filter)

    total = session.execute(count_query).scalar_one()
    rows = session.execute(
        query.order_by(BugReport.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return PaginatedBugReports(
        items=[
            _summary_out(
                report,
                comment_count=comment_count,
                last_comment_at=last_comment_at,
            )
            for report, comment_count, last_comment_at in rows
        ],
        total=total,
    )


class BugReportImportFileResult(BaseModel):
    filename: str
    status: Literal["imported", "already_exists", "error"]
    detail: str | None = None


class BugReportImportSummary(BaseModel):
    results: list[BugReportImportFileResult]


@router.post("/admin/bug-reports/import", response_model=BugReportImportSummary)
def import_bug_reports(
    session: Session = Depends(get_session),
    _admin: Soldier = Depends(require_roles("admin")),
    files: list[UploadFile] = File(...),
) -> BugReportImportSummary:
    if len(files) > _MAX_IMPORT_FILES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="too_many_files")

    results: list[BugReportImportFileResult] = []
    for f in files:
        name = f.filename or "unnamed.json"
        raw = f.file.read(_MAX_IMPORT_FILE_BYTES + 1)
        if len(raw) > _MAX_IMPORT_FILE_BYTES:
            results.append(BugReportImportFileResult(filename=name, status="error", detail="file_too_large"))
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            results.append(BugReportImportFileResult(filename=name, status="error", detail="invalid_json"))
            continue
        if not isinstance(payload, dict):
            results.append(BugReportImportFileResult(filename=name, status="error", detail="invalid_json"))
            continue
        try:
            svc.import_bug_report_json(session, payload)
        except svc.BugReportImportError as exc:
            status_value = "already_exists" if str(exc) == "already_exists" else "error"
            results.append(BugReportImportFileResult(filename=name, status=status_value, detail=str(exc)))
            continue
        results.append(BugReportImportFileResult(filename=name, status="imported"))
    session.commit()
    return BugReportImportSummary(results=results)


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
    return Response(content=path.read_text(encoding="utf-8"), media_type="application/json")


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
    report.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(report)
    return _summary_with_comment_aggregates(session, report)


def _has_unseen_activity(report: BugReport, last_comment_at: datetime | None) -> bool:
    seen_at = report.reporter_last_seen_at
    unseen_comment = last_comment_at is not None and (seen_at is None or last_comment_at > seen_at)
    unseen_status = report.updated_at > report.created_at and (seen_at is None or report.updated_at > seen_at)
    return unseen_comment or unseen_status


@router.get("/my/bug-reports", response_model=PaginatedBugReports)
def list_my_bug_reports(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PaginatedBugReports:
    """Reporters' own bug reports, reusing the same `_summary_out` serializer
    (and `BugReportSummaryOut`/`PaginatedBugReports` response shape) as
    `GET /admin/bug-reports` so the frontend can share one client-side type."""
    comment_aggregates = _comment_aggregates_subquery()
    rows = session.execute(
        select(
            BugReport,
            func.coalesce(comment_aggregates.c.comment_count, 0).label("comment_count"),
            comment_aggregates.c.last_comment_at,
        )
        .outerjoin(comment_aggregates, comment_aggregates.c.bug_report_id == BugReport.id)
        .where(BugReport.reporter_id == user.id)
        .order_by(BugReport.created_at.desc())
    ).all()
    return PaginatedBugReports(
        items=[
            _summary_out(
                report,
                comment_count=comment_count,
                last_comment_at=last_comment_at,
                has_unseen_activity=_has_unseen_activity(report, last_comment_at),
            )
            for report, comment_count, last_comment_at in rows
        ],
        total=len(rows),
    )


class UnseenCountOut(BaseModel):
    count: int


@router.get("/my/bug-reports/unseen-count", response_model=UnseenCountOut)
def get_my_bug_reports_unseen_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> UnseenCountOut:
    comment_aggregates = _comment_aggregates_subquery()
    rows = session.execute(
        select(BugReport, comment_aggregates.c.last_comment_at)
        .outerjoin(comment_aggregates, comment_aggregates.c.bug_report_id == BugReport.id)
        .where(BugReport.reporter_id == user.id)
    ).all()
    count = sum(1 for report, last_comment_at in rows if _has_unseen_activity(report, last_comment_at))
    return UnseenCountOut(count=count)


class BugReportCommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class BugReportCommentAttachmentOut(BaseModel):
    id: uuid.UUID
    file_name: str
    content_type: str


class BugReportCommentOut(BaseModel):
    id: uuid.UUID
    bug_report_id: uuid.UUID
    author_id: uuid.UUID
    author_name: str
    body: str
    created_at: datetime
    # Embedded like ExemptionRequest.files (see exemption_requests.py) rather than
    # requiring a second round-trip per comment to discover its attachments.
    attachments: list[BugReportCommentAttachmentOut] = Field(default_factory=list)


def _require_reporter_or_admin(session: Session, user: Soldier, report_id: uuid.UUID) -> BugReport:
    report = session.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    # Soldier.role is a single string field ("admin" is one possible value), not a
    # list — matches the `user.role == "admin"` convention used throughout this
    # codebase (e.g. exemption_requests.py's escalate_commander_exemption_route).
    # The existing admin-only endpoints in this file use the require_roles("admin")
    # dependency instead, but that dependency can't express "OR the reporter", so
    # this inline check is the ownership-fallback equivalent.
    if report.reporter_id != user.id and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return report


@router.post("/bug-reports/{report_id}/seen", status_code=status.HTTP_204_NO_CONTENT)
def mark_bug_report_seen(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    report = session.get(BugReport, report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if report.reporter_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    report.reporter_last_seen_at = datetime.now(UTC)
    session.commit()


@router.post(
    "/bug-reports/{report_id}/comments",
    response_model=BugReportCommentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_bug_report_comment(
    report_id: uuid.UUID,
    body: BugReportCommentBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BugReportCommentOut:
    report = _require_reporter_or_admin(session, user, report_id)
    existing_count = session.execute(
        select(func.count()).select_from(BugReportComment).where(BugReportComment.bug_report_id == report_id)
    ).scalar_one()
    if existing_count >= MAX_COMMENTS_PER_REPORT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="too_many_comments")
    comment = BugReportComment(bug_report_id=report_id, author_id=user.id, body=body.body)
    session.add(comment)
    session.commit()
    session.refresh(comment)
    if comment.author_id != report.reporter_id:
        create_notification(
            session,
            soldier_id=report.reporter_id,
            type=NotificationType.bug_report_comment,
            title="תגובה חדשה לדיווח באג",
            reference_type="bug_report",
            reference_id=report.id,
            actor_id=user.id,
        )
    else:
        report.reporter_last_seen_at = comment.created_at
    session.commit()
    return BugReportCommentOut(
        id=comment.id,
        bug_report_id=comment.bug_report_id,
        author_id=comment.author_id,
        author_name=user.full_name,
        body=comment.body,
        created_at=comment.created_at,
        attachments=[],
    )


@router.get("/bug-reports/{report_id}/comments", response_model=list[BugReportCommentOut])
def list_bug_report_comments(
    report_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[BugReportCommentOut]:
    _require_reporter_or_admin(session, user, report_id)
    comments = session.execute(
        select(BugReportComment)
        .where(BugReportComment.bug_report_id == report_id)
        .order_by(BugReportComment.created_at)
    ).scalars().all()
    author_ids = {c.author_id for c in comments}
    authors = (
        {s.id: s.full_name for s in session.execute(select(Soldier).where(Soldier.id.in_(author_ids))).scalars().all()}
        if author_ids
        else {}
    )
    comment_ids = [c.id for c in comments]
    attachments_by_comment: dict[uuid.UUID, list[BugReportCommentAttachmentOut]] = {cid: [] for cid in comment_ids}
    if comment_ids:
        attachments = session.execute(
            select(BugReportCommentAttachment)
            .where(BugReportCommentAttachment.comment_id.in_(comment_ids))
            .order_by(BugReportCommentAttachment.created_at)
        ).scalars().all()
        for a in attachments:
            attachments_by_comment[a.comment_id].append(
                BugReportCommentAttachmentOut(id=a.id, file_name=a.file_name, content_type=a.content_type)
            )
    return [
        BugReportCommentOut(
            id=c.id,
            bug_report_id=c.bug_report_id,
            author_id=c.author_id,
            author_name=authors.get(c.author_id, "?"),
            body=c.body,
            created_at=c.created_at,
            attachments=attachments_by_comment.get(c.id, []),
        )
        for c in comments
    ]


@router.post(
    "/bug-reports/{report_id}/comments/{comment_id}/attachments",
    response_model=BugReportCommentAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_bug_report_comment_attachment(
    report_id: uuid.UUID,
    comment_id: uuid.UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BugReportCommentAttachmentOut:
    _require_reporter_or_admin(session, user, report_id)
    comment = session.get(BugReportComment, comment_id)
    if comment is None or comment.bug_report_id != report_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if comment.author_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    existing_count = session.execute(
        select(func.count()).select_from(BugReportCommentAttachment).where(
            BugReportCommentAttachment.comment_id == comment_id
        )
    ).scalar_one()
    if existing_count >= MAX_ATTACHMENTS_PER_COMMENT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="too_many_attachments")
    data = await file.read(_MAX_COMMENT_ATTACHMENT_BYTES + 1)
    if len(data) > _MAX_COMMENT_ATTACHMENT_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file_too_large")
    if file.content_type not in _ALLOWED_COMMENT_ATTACHMENT_TYPES or not _comment_attachment_magic_bytes_match(
        file.content_type, data
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_file_type")
    safe_name = re.sub(r"[^\w.\-]", "_", (file.filename or "attachment")).replace("..", "_")[:200]
    attachment = BugReportCommentAttachment(
        comment_id=comment_id,
        file_name=safe_name,
        content_type=file.content_type,
        data=data,
        uploaded_by=user.id,
    )
    session.add(attachment)
    session.commit()
    return BugReportCommentAttachmentOut(id=attachment.id, file_name=attachment.file_name, content_type=attachment.content_type)


@router.get("/bug-reports/{report_id}/comments/{comment_id}/attachments/{attachment_id}")
def download_bug_report_comment_attachment(
    report_id: uuid.UUID,
    comment_id: uuid.UUID,
    attachment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Response:
    _require_reporter_or_admin(session, user, report_id)
    comment = session.get(BugReportComment, comment_id)
    if comment is None or comment.bug_report_id != report_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    attachment = session.get(BugReportCommentAttachment, attachment_id)
    if attachment is None or attachment.comment_id != comment_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return Response(
        content=attachment.data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": f'attachment; filename="{attachment.file_name}"'},
    )
