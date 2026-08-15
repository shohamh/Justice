from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BugReport, BugReportComment, BugReportCommentAttachment, Soldier

_ACTIVE_STATUSES = ("open", "in_progress")
_VALID_SEVERITIES = ("low", "medium", "high")
_ATTACHMENT_EXTENSION_BY_CONTENT_TYPE = {
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/png": "png",
}
_MISSING_SCREENSHOT_NOTICE = "תמונת המסך המקורית אינה זמינה בייצוא זה."
_MISSING_ATTACHMENT_NOTICE = "קובץ המצורף אינו זמין בייצוא זה."


def _utc_now() -> datetime:
    return datetime.now(UTC)


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


def _load_comments_for_reports(
    session: Session,
    report_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[BugReportComment]]:
    comments_by_report: dict[uuid.UUID, list[BugReportComment]] = {report_id: [] for report_id in report_ids}
    if not report_ids:
        return comments_by_report

    comments = session.execute(
        select(BugReportComment)
        .where(BugReportComment.bug_report_id.in_(report_ids))
        .order_by(BugReportComment.created_at, BugReportComment.id)
    ).scalars().all()
    for comment in comments:
        comments_by_report.setdefault(comment.bug_report_id, []).append(comment)
    return comments_by_report


def _load_attachments_for_comments(
    session: Session,
    comment_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[BugReportCommentAttachment]]:
    attachments_by_comment: dict[uuid.UUID, list[BugReportCommentAttachment]] = {comment_id: [] for comment_id in comment_ids}
    if not comment_ids:
        return attachments_by_comment

    attachments = session.execute(
        select(BugReportCommentAttachment)
        .where(BugReportCommentAttachment.comment_id.in_(comment_ids))
        .order_by(BugReportCommentAttachment.created_at, BugReportCommentAttachment.id)
    ).scalars().all()
    for attachment in attachments:
        attachments_by_comment.setdefault(attachment.comment_id, []).append(attachment)
    return attachments_by_comment


def _load_author_names(
    session: Session,
    author_ids: set[uuid.UUID],
) -> dict[uuid.UUID, str]:
    if not author_ids:
        return {}
    authors = session.execute(
        select(Soldier).where(Soldier.id.in_(author_ids))
    ).scalars().all()
    return {author.id: author.full_name for author in authors}


def _json_block(value: Any) -> str:
    if value in (None, [], {}):
        return "_None_\n"
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return f"```json\n{rendered}\n```\n"


def _report_markdown_path(report: BugReport) -> str:
    return f"reports/{report.id}.md"


def _report_image_dir(report: BugReport) -> str:
    return f"images/{report.id}"


def _report_screenshot_path(report: BugReport) -> str:
    return f"{_report_image_dir(report)}/original-screenshot.png"


def _comment_attachment_path(
    report: BugReport,
    attachment: BugReportCommentAttachment,
    index: int,
) -> str:
    extension = _ATTACHMENT_EXTENSION_BY_CONTENT_TYPE.get(attachment.content_type, "bin")
    return f"{_report_image_dir(report)}/comment-{attachment.comment_id}-{index}.{extension}"


def _render_index_markdown(
    reports: list[BugReport],
    *,
    scope: Literal["all_active", "filtered"],
    exported_at: datetime,
) -> str:
    lines = [
        "# Bug Report Export",
        "",
        f"Exported at: {exported_at.isoformat()}",
        f"Scope: {scope}",
        f"Count: {len(reports)}",
        "",
    ]
    if not reports:
        lines.append("No active bug reports matched this export.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Reports")
    lines.append("")
    for report in reports:
        lines.append(f"- [{report.id}]({_report_markdown_path(report)})")
    lines.append("")
    return "\n".join(lines)


def _render_report_markdown(
    report: BugReport,
    *,
    comments: list[BugReportComment],
    attachments_by_comment: dict[uuid.UUID, list[BugReportCommentAttachment]],
    author_names: dict[uuid.UUID, str],
) -> str:
    lines = [
        f"# Bug Report {report.id}",
        "",
        "## Triage Metadata",
        "",
        f"- Severity: {report.severity}",
        f"- Status: {report.status}",
        f"- Created At: {report.created_at.isoformat()}",
        f"- Updated At: {report.updated_at.isoformat()}",
        "",
        "## Description",
        "",
        report.description,
        "",
        "## Route",
        "",
        report.route,
        "",
        "## Navigation History",
        "",
        _json_block(report.nav_history),
        "## User Snapshot",
        "",
        _json_block(report.user_snapshot),
        "## Audit Snapshot",
        "",
        _json_block(report.audit_snapshot),
        "## Original Screenshot",
        "",
    ]

    if report.screenshot:
        lines.extend(
            [
                f"![Original screenshot](../{_report_screenshot_path(report)})",
                "",
            ]
        )
    else:
        lines.extend(
            [
                _MISSING_SCREENSHOT_NOTICE,
                "",
            ]
        )

    lines.extend(
        [
            "## Comments",
            "",
        ]
    )
    if not comments:
        lines.extend(
            [
                "_No comments._",
                "",
            ]
        )
        return "\n".join(lines)

    for comment in comments:
        author_name = author_names.get(comment.author_id, "?")
        lines.extend(
            [
                f"### {comment.created_at.isoformat()} - {author_name}",
                "",
                comment.body,
                "",
            ]
        )
        attachments = attachments_by_comment.get(comment.id, [])
        if not attachments:
            lines.extend(
                [
                    "_No attachments._",
                    "",
                ]
            )
            continue

        lines.append("Attachments:")
        lines.append("")
        for index, attachment in enumerate(attachments, start=1):
            if attachment.data:
                attachment_path = _comment_attachment_path(report, attachment, index)
                lines.append(f"- [Attachment {index}](../{attachment_path})")
            else:
                lines.append(f"- {_MISSING_ATTACHMENT_NOTICE}")
        lines.append("")

    return "\n".join(lines)


def _render_bug_report_export_zip(
    reports: list[BugReport],
    *,
    scope: Literal["all_active", "filtered"],
    exported_at: datetime,
    comments_by_report: dict[uuid.UUID, list[BugReportComment]],
    attachments_by_comment: dict[uuid.UUID, list[BugReportCommentAttachment]],
    author_names: dict[uuid.UUID, str],
) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "index.md",
            _render_index_markdown(reports, scope=scope, exported_at=exported_at).encode("utf-8"),
        )

        for report in reports:
            report_comments = comments_by_report.get(report.id, [])
            archive.writestr(
                _report_markdown_path(report),
                _render_report_markdown(
                    report,
                    comments=report_comments,
                    attachments_by_comment=attachments_by_comment,
                    author_names=author_names,
                ).encode("utf-8"),
            )

            if report.screenshot:
                archive.writestr(_report_screenshot_path(report), report.screenshot)

            for comment in report_comments:
                for index, attachment in enumerate(attachments_by_comment.get(comment.id, []), start=1):
                    if attachment.data:
                        archive.writestr(_comment_attachment_path(report, attachment, index), attachment.data)
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
    report_ids = [report.id for report in reports]
    comments_by_report = _load_comments_for_reports(session, report_ids)
    comment_ids = [comment.id for comments in comments_by_report.values() for comment in comments]
    attachments_by_comment = _load_attachments_for_comments(session, comment_ids)
    author_ids = {comment.author_id for comments in comments_by_report.values() for comment in comments}
    author_names = _load_author_names(session, author_ids)
    return _render_bug_report_export_zip(
        reports,
        scope=scope,
        exported_at=_utc_now(),
        comments_by_report=comments_by_report,
        attachments_by_comment=attachments_by_comment,
        author_names=author_names,
    )
