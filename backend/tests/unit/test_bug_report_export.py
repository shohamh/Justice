from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.db.models import BugReport, BugReportComment, BugReportCommentAttachment
from app.services.bug_report_export import build_bug_report_export_zip
from tests.helpers import create_soldier

_PNG_BYTES = b"\x89PNG\r\n\x1a\npng-test"
_GIF_BYTES = b"GIF89agif-test"


def _create_bug_report(
    session,
    *,
    severity: str,
    status: str,
    created_at: datetime,
    description: str | None = None,
    route: str = "/bug-reports",
    reporter_id=None,
    screenshot: bytes | None = None,
    nav_history=None,
    audit_snapshot=None,
    user_snapshot=None,
) -> BugReport:
    report = BugReport(
        reporter_id=reporter_id,
        description=description or f"{severity}-{status}",
        severity=severity,
        route=route,
        status=status,
        screenshot=screenshot,
        nav_history=nav_history,
        audit_snapshot=audit_snapshot,
        user_snapshot=user_snapshot,
        json_file_path=None,
    )
    report.created_at = created_at
    report.updated_at = created_at
    session.add(report)
    session.flush()
    return report


def _create_comment(
    session,
    *,
    report: BugReport,
    author_id,
    body: str,
    created_at: datetime,
) -> BugReportComment:
    comment = BugReportComment(
        bug_report_id=report.id,
        author_id=author_id,
        body=body,
    )
    comment.created_at = created_at
    session.add(comment)
    session.flush()
    return comment


def _create_attachment(
    session,
    *,
    comment: BugReportComment,
    file_name: str,
    content_type: str,
    data: bytes,
    created_at: datetime,
) -> BugReportCommentAttachment:
    attachment = BugReportCommentAttachment(
        comment_id=comment.id,
        file_name=file_name,
        content_type=content_type,
        data=data,
        uploaded_by=comment.author_id,
    )
    attachment.created_at = created_at
    session.add(attachment)
    session.flush()
    return attachment


def _capture_rendered_reports(monkeypatch):
    captured: dict[str, list[BugReport]] = {}

    def _fake_render(reports, *args, **kwargs):
        captured["reports"] = list(reports)
        return b"zip-bytes"

    monkeypatch.setattr("app.services.bug_report_export._render_bug_report_export_zip", _fake_render)
    return captured


def _read_archive(archive_bytes: bytes) -> tuple[list[str], dict[str, str], dict[str, bytes]]:
    with ZipFile(BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        text_entries = {
            name: archive.read(name).decode("utf-8")
            for name in names
            if name.endswith(".md")
        }
        binary_entries = {
            name: archive.read(name)
            for name in names
            if not name.endswith(".md")
        }
    return names, text_entries, binary_entries


def test_build_bug_report_export_zip_all_active_selects_only_open_and_in_progress(
    admin_session,
    monkeypatch,
):
    open_report = _create_bug_report(
        admin_session,
        severity="low",
        status="open",
        created_at=datetime(2026, 8, 14, 8, 0, tzinfo=timezone.utc),
    )
    in_progress_report = _create_bug_report(
        admin_session,
        severity="high",
        status="in_progress",
        created_at=datetime(2026, 8, 14, 8, 1, tzinfo=timezone.utc),
    )
    resolved_report = _create_bug_report(
        admin_session,
        severity="low",
        status="resolved",
        created_at=datetime(2026, 8, 14, 8, 2, tzinfo=timezone.utc),
    )
    wont_fix_report = _create_bug_report(
        admin_session,
        severity="high",
        status="wont_fix",
        created_at=datetime(2026, 8, 14, 8, 3, tzinfo=timezone.utc),
    )

    captured = _capture_rendered_reports(monkeypatch)

    archive_bytes = build_bug_report_export_zip(
        admin_session,
        scope="all_active",
        severity=None,
        status=None,
    )

    assert archive_bytes == b"zip-bytes"
    assert {report.id for report in captured["reports"]} == {
        open_report.id,
        in_progress_report.id,
    }
    assert resolved_report.id not in {report.id for report in captured["reports"]}
    assert wont_fix_report.id not in {report.id for report in captured["reports"]}


def test_build_bug_report_export_zip_filtered_applies_severity_and_active_status(
    admin_session,
    monkeypatch,
):
    open_low = _create_bug_report(
        admin_session,
        severity="low",
        status="open",
        created_at=datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc),
    )
    _create_bug_report(
        admin_session,
        severity="high",
        status="open",
        created_at=datetime(2026, 8, 14, 9, 1, tzinfo=timezone.utc),
    )
    _create_bug_report(
        admin_session,
        severity="low",
        status="in_progress",
        created_at=datetime(2026, 8, 14, 9, 2, tzinfo=timezone.utc),
    )
    _create_bug_report(
        admin_session,
        severity="low",
        status="resolved",
        created_at=datetime(2026, 8, 14, 9, 3, tzinfo=timezone.utc),
    )
    _create_bug_report(
        admin_session,
        severity="low",
        status="wont_fix",
        created_at=datetime(2026, 8, 14, 9, 4, tzinfo=timezone.utc),
    )

    captured = _capture_rendered_reports(monkeypatch)

    archive_bytes = build_bug_report_export_zip(
        admin_session,
        scope="filtered",
        severity="low",
        status="open",
    )

    assert archive_bytes == b"zip-bytes"
    assert [report.id for report in captured["reports"]] == [open_low.id]


@pytest.mark.parametrize("status_input", ["resolved", "wont_fix"])
def test_build_bug_report_export_zip_never_selects_inactive_status_inputs(
    admin_session,
    monkeypatch,
    status_input,
):
    open_low = _create_bug_report(
        admin_session,
        severity="low",
        status="open",
        created_at=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
    )
    in_progress_low = _create_bug_report(
        admin_session,
        severity="low",
        status="in_progress",
        created_at=datetime(2026, 8, 14, 10, 1, tzinfo=timezone.utc),
    )
    resolved_low = _create_bug_report(
        admin_session,
        severity="low",
        status="resolved",
        created_at=datetime(2026, 8, 14, 10, 2, tzinfo=timezone.utc),
    )
    wont_fix_low = _create_bug_report(
        admin_session,
        severity="low",
        status="wont_fix",
        created_at=datetime(2026, 8, 14, 10, 3, tzinfo=timezone.utc),
    )

    captured = _capture_rendered_reports(monkeypatch)

    archive_bytes = build_bug_report_export_zip(
        admin_session,
        scope="filtered",
        severity="low",
        status=status_input,
    )

    assert archive_bytes == b"zip-bytes"
    assert {report.id for report in captured["reports"]} == {open_low.id, in_progress_low.id}
    assert resolved_low.id not in {report.id for report in captured["reports"]}
    assert wont_fix_low.id not in {report.id for report in captured["reports"]}


def test_build_bug_report_export_zip_renders_markdown_zip_and_relative_links(
    admin_session,
    monkeypatch,
):
    reporter = create_soldier(
        admin_session,
        personal_number="bugexport001",
        full_name="Reporter One",
    )
    commenter = create_soldier(
        admin_session,
        personal_number="bugexport002",
        full_name="Commander Commenter",
        role="admin",
    )
    older_report = _create_bug_report(
        admin_session,
        reporter_id=reporter.id,
        severity="high",
        status="open",
        description="Calendar opens to a blank screen",
        route="/calendar",
        screenshot=_PNG_BYTES,
        nav_history=[
            {"path": "/", "timestamp": "2026-08-14T10:00:00Z"},
            {"path": "/calendar", "timestamp": "2026-08-14T10:01:00Z"},
        ],
        audit_snapshot=[{"action": "login", "entity_type": "soldier"}],
        user_snapshot={"full_name": reporter.full_name, "role": reporter.role},
        created_at=datetime(2026, 8, 14, 10, 2, tzinfo=timezone.utc),
    )
    newer_report = _create_bug_report(
        admin_session,
        reporter_id=reporter.id,
        severity="low",
        status="in_progress",
        description="Secondary report",
        route="/duties",
        created_at=datetime(2026, 8, 14, 10, 5, tzinfo=timezone.utc),
    )
    first_comment = _create_comment(
        admin_session,
        report=older_report,
        author_id=commenter.id,
        body="בודק את זה עכשיו",
        created_at=datetime(2026, 8, 14, 10, 3, tzinfo=timezone.utc),
    )
    _create_attachment(
        admin_session,
        comment=first_comment,
        file_name="../../weird name.gif",
        content_type="image/gif",
        data=_GIF_BYTES,
        created_at=datetime(2026, 8, 14, 10, 4, tzinfo=timezone.utc),
    )
    _create_comment(
        admin_session,
        report=older_report,
        author_id=reporter.id,
        body="עדיין קורה גם אחרי רענון",
        created_at=datetime(2026, 8, 14, 10, 6, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(
        "app.services.bug_report_export._utc_now",
        lambda: datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
    )

    archive_bytes = build_bug_report_export_zip(
        admin_session,
        scope="all_active",
        severity=None,
        status=None,
    )
    names, text_entries, binary_entries = _read_archive(archive_bytes)

    older_report_id = str(older_report.id)
    newer_report_id = str(newer_report.id)
    first_comment_id = str(first_comment.id)

    assert "index.md" in names
    assert f"reports/{older_report_id}.md" in names
    assert f"reports/{newer_report_id}.md" in names
    assert f"images/{older_report_id}/original-screenshot.png" in names
    assert f"images/{older_report_id}/comment-{first_comment_id}-1.gif" in names
    assert all("weird name" not in name for name in names)
    assert all(".." not in name for name in names)

    index_md = text_entries["index.md"]
    assert "Exported at: 2026-08-14T15:00:00+03:00" in index_md
    assert "Scope: all_active" in index_md
    assert "Count: 2" in index_md
    assert index_md.index(f"(reports/{newer_report_id}.md)") < index_md.index(f"(reports/{older_report_id}.md)")

    report_md = text_entries[f"reports/{older_report_id}.md"]
    assert "## Triage Metadata" in report_md
    assert "Calendar opens to a blank screen" in report_md
    assert "/calendar" in report_md
    assert '"/calendar"' in report_md
    assert "Reporter One" in report_md
    assert '"action": "login"' in report_md
    assert f"![Original screenshot](../images/{older_report_id}/original-screenshot.png)" in report_md
    assert f"\n[Original screenshot](../images/{older_report_id}/original-screenshot.png)" not in report_md
    assert f"../images/{older_report_id}/comment-{first_comment_id}-1.gif" in report_md
    assert report_md.index("בודק את זה עכשיו") < report_md.index("עדיין קורה גם אחרי רענון")

    assert binary_entries[f"images/{older_report_id}/original-screenshot.png"] == _PNG_BYTES
    assert binary_entries[f"images/{older_report_id}/comment-{first_comment_id}-1.gif"] == _GIF_BYTES


def test_build_bug_report_export_zip_inlines_hebrew_notice_for_missing_images(
    admin_session,
    monkeypatch,
):
    reporter = create_soldier(admin_session, personal_number="bugexport003", full_name="Reporter Missing")
    report = _create_bug_report(
        admin_session,
        reporter_id=reporter.id,
        severity="medium",
        status="open",
        description="Missing image data",
        route="/missing",
        screenshot=b"",
        user_snapshot={"full_name": reporter.full_name},
        created_at=datetime(2026, 8, 14, 11, 0, tzinfo=timezone.utc),
    )
    comment = _create_comment(
        admin_session,
        report=report,
        author_id=reporter.id,
        body="Attachment vanished",
        created_at=datetime(2026, 8, 14, 11, 1, tzinfo=timezone.utc),
    )
    _create_attachment(
        admin_session,
        comment=comment,
        file_name="gone.png",
        content_type="image/png",
        data=b"",
        created_at=datetime(2026, 8, 14, 11, 2, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(
        "app.services.bug_report_export._utc_now",
        lambda: datetime(2026, 8, 14, 12, 30, tzinfo=timezone.utc),
    )

    archive_bytes = build_bug_report_export_zip(
        admin_session,
        scope="all_active",
        severity=None,
        status=None,
    )
    names, text_entries, _ = _read_archive(archive_bytes)

    report_md = text_entries[f"reports/{report.id}.md"]

    assert f"images/{report.id}/original-screenshot.png" not in names
    assert "תמונת המסך המקורית אינה זמינה בייצוא זה." in report_md
    assert "קובץ המצורף אינו זמין בייצוא זה." in report_md
    assert all("warning" not in name.lower() for name in names)


def test_build_bug_report_export_zip_zero_match_archive_has_explanatory_index(
    admin_session,
    monkeypatch,
):
    _create_bug_report(
        admin_session,
        severity="low",
        status="resolved",
        created_at=datetime(2026, 8, 14, 11, 30, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(
        "app.services.bug_report_export._utc_now",
        lambda: datetime(2026, 8, 14, 13, 0, tzinfo=timezone.utc),
    )

    archive_bytes = build_bug_report_export_zip(
        admin_session,
        scope="all_active",
        severity=None,
        status=None,
    )
    names, text_entries, _ = _read_archive(archive_bytes)

    assert names == ["index.md"]
    assert "Count: 0" in text_entries["index.md"]
    assert "No active bug reports matched this export." in text_entries["index.md"]
