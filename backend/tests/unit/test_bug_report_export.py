from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.models import BugReport
from app.services.bug_report_export import build_bug_report_export_zip


def _create_bug_report(
    session,
    *,
    severity: str,
    status: str,
    created_at: datetime,
) -> BugReport:
    report = BugReport(
        description=f"{severity}-{status}",
        severity=severity,
        route="/bug-reports",
        status=status,
        screenshot=None,
        nav_history=None,
        audit_snapshot=None,
        user_snapshot=None,
        json_file_path=None,
    )
    report.created_at = created_at
    report.updated_at = created_at
    session.add(report)
    session.flush()
    return report


def _capture_rendered_reports(monkeypatch):
    captured: dict[str, list[BugReport]] = {}

    def _fake_render(reports):
        captured["reports"] = list(reports)
        return b"zip-bytes"

    monkeypatch.setattr("app.services.bug_report_export._render_bug_report_export_zip", _fake_render)
    return captured


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
