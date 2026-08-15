from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import BugReport, BugReportComment
from app.services import bug_reports as svc
from tests.helpers import auth_headers, create_soldier

# Canonical 1x1 transparent PNG. The magic-byte prefix ("iVBORw0KGgo" -> the PNG
# signature) is what the backend actually validates.
_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


@pytest.fixture(autouse=True)
def _isolate_log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)


def test_submit_bug_report_creates_row(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi001")

    resp = client.post(
        "/api/bug-reports",
        json={
            "description": "the calendar is blank",
            "severity": "high",
            "screenshot": _TINY_PNG_B64,
            "route": "/calendar",
            "nav_history": [{"path": "/", "timestamp": "2026-07-25T10:00:00Z"}],
        },
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 201
    assert resp.json() == {"status": "ok"}

    row = admin_session.query(BugReport).filter_by(reporter_id=soldier.id).one()
    assert row.severity == "high"
    assert row.screenshot is not None


def test_submit_bug_report_without_screenshot(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi002")

    resp = client.post(
        "/api/bug-reports",
        json={"description": "no screenshot captured", "severity": "low", "route": "/"},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 201
    row = admin_session.query(BugReport).filter_by(reporter_id=soldier.id).one()
    assert row.screenshot is None


def test_submit_bug_report_requires_auth(client: TestClient):
    resp = client.post("/api/bug-reports", json={"description": "x", "severity": "low", "route": "/"})
    assert resp.status_code == 401


def test_submit_bug_report_rejects_bad_severity(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi003")
    resp = client.post(
        "/api/bug-reports",
        json={"description": "x", "severity": "urgent", "route": "/"},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 422


def test_submit_bug_report_rejects_empty_description(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi004")
    resp = client.post(
        "/api/bug-reports",
        json={"description": "", "severity": "low", "route": "/"},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 422


def test_submit_bug_report_drops_invalid_screenshot_data(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi005")
    resp = client.post(
        "/api/bug-reports",
        json={"description": "x", "severity": "low", "route": "/", "screenshot": "not-base64-png-data!!!"},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 201
    row = admin_session.query(BugReport).filter_by(reporter_id=soldier.id).one()
    assert row.screenshot is None


def test_submit_bug_report_rejects_oversized_screenshot(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi006")
    oversized_b64 = "A" * (7 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/bug-reports",
        json={"description": "x", "severity": "low", "route": "/", "screenshot": oversized_b64},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 422


def test_submit_bug_report_rejects_oversized_route(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi007")
    resp = client.post(
        "/api/bug-reports",
        json={"description": "x", "severity": "low", "route": "/" + "a" * 501},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 422


def test_submit_bug_report_rejects_too_many_nav_history_entries(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi008")
    nav_history = [{"path": "/", "timestamp": "2026-07-25T10:00:00Z"} for _ in range(16)]
    resp = client.post(
        "/api/bug-reports",
        json={"description": "x", "severity": "low", "route": "/", "nav_history": nav_history},
        headers=auth_headers(soldier),
    )
    assert resp.status_code == 422


def _submit(client: TestClient, reporter, **overrides):
    body = {"description": "x", "severity": "low", "route": "/"}
    body.update(overrides)
    resp = client.post("/api/bug-reports", json=body, headers=auth_headers(reporter))
    assert resp.status_code == 201
    return resp


def _read_zip_text_entries(data: bytes) -> dict[str, str]:
    with ZipFile(BytesIO(data)) as archive:
        return {
            name: archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.endswith(".md")
        }


def _create_comment(
    session: Session,
    *,
    report_id: uuid.UUID,
    author_id: uuid.UUID,
    body: str,
) -> BugReportComment:
    comment = BugReportComment(
        bug_report_id=report_id,
        author_id=author_id,
        body=body,
    )
    session.add(comment)
    session.flush()
    return comment


def test_list_bug_reports_requires_admin(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi010")
    resp = client.get("/api/admin/bug-reports", headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_list_bug_reports_filters_by_severity_and_paginates(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi011", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi012")
    for sev in ("low", "medium", "high"):
        _submit(client, reporter, description=f"bug-{sev}", severity=sev)

    resp = client.get("/api/admin/bug-reports", params={"severity": "high"}, headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["severity"] == "high"

    resp = client.get("/api/admin/bug-reports", params={"limit": 1, "offset": 0}, headers=auth_headers(admin))
    assert len(resp.json()["items"]) == 1
    assert resp.json()["total"] == 3


def test_export_bug_reports_requires_admin(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugapi010a")

    resp = client.get("/api/admin/bug-reports/export", headers=auth_headers(soldier))

    assert resp.status_code == 403


def test_export_bug_reports_returns_zip_headers_and_content_for_admin(
    client: TestClient,
    admin_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    admin = create_soldier(admin_session, personal_number="bugapi011a", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi012a")
    _submit(
        client,
        reporter,
        description="calendar export regression",
        severity="high",
        screenshot=_TINY_PNG_B64,
        route="/calendar",
    )

    exported_at = datetime(2026, 8, 14, 18, 4, tzinfo=timezone(timedelta(hours=3)))
    monkeypatch.setattr("app.routes.bug_reports.get_bug_report_export_timestamp", lambda: exported_at)

    resp = client.get("/api/admin/bug-reports/export", headers=auth_headers(admin))

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    disposition = resp.headers["content-disposition"]
    assert disposition == 'attachment; filename="bug-reports-2026-08-14-1804.zip"'
    text_entries = _read_zip_text_entries(resp.content)
    assert "index.md" in text_entries
    assert "Exported at: 2026-08-14T18:04:00+03:00" in text_entries["index.md"]
    assert "Count: 1" in text_entries["index.md"]
    assert "calendar export regression" in "\n".join(text_entries.values())


def test_export_bug_reports_all_active_scope_excludes_resolved_and_wont_fix(
    client: TestClient,
    admin_session: Session,
):
    admin = create_soldier(admin_session, personal_number="bugapi011b", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi012b")
    _submit(client, reporter, description="open export item", severity="low")
    _submit(client, reporter, description="in progress export item", severity="medium")
    _submit(client, reporter, description="resolved export item", severity="high")
    _submit(client, reporter, description="wont-fix export item", severity="low")

    reports = admin_session.query(BugReport).order_by(BugReport.created_at).all()
    report_ids_by_description = {report.description: report.id for report in reports}
    admin_session.get(BugReport, report_ids_by_description["in progress export item"]).status = "in_progress"
    admin_session.get(BugReport, report_ids_by_description["resolved export item"]).status = "resolved"
    admin_session.get(BugReport, report_ids_by_description["wont-fix export item"]).status = "wont_fix"
    admin_session.commit()

    resp = client.get("/api/admin/bug-reports/export", headers=auth_headers(admin))

    assert resp.status_code == 200
    text_entries = _read_zip_text_entries(resp.content)
    joined_text = "\n".join(text_entries.values())
    assert "open export item" in joined_text
    assert "in progress export item" in joined_text
    assert "resolved export item" not in joined_text
    assert "wont-fix export item" not in joined_text


def test_export_bug_reports_filtered_scope_applies_severity_and_status(
    client: TestClient,
    admin_session: Session,
):
    admin = create_soldier(admin_session, personal_number="bugapi011c", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi012c")
    _submit(client, reporter, description="target filtered item", severity="high")
    _submit(client, reporter, description="wrong severity item", severity="low")
    _submit(client, reporter, description="wrong status item", severity="high")

    reports = admin_session.query(BugReport).order_by(BugReport.created_at).all()
    report_ids_by_description = {report.description: report.id for report in reports}
    admin_session.get(BugReport, report_ids_by_description["target filtered item"]).status = "in_progress"
    admin_session.get(BugReport, report_ids_by_description["wrong severity item"]).status = "in_progress"
    admin_session.get(BugReport, report_ids_by_description["wrong status item"]).status = "open"
    admin_session.commit()

    resp = client.get(
        "/api/admin/bug-reports/export",
        params={"scope": "filtered", "severity": "high", "status": "in_progress"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    text_entries = _read_zip_text_entries(resp.content)
    joined_text = "\n".join(text_entries.values())
    assert "target filtered item" in joined_text
    assert "wrong severity item" not in joined_text
    assert "wrong status item" not in joined_text


def test_export_bug_reports_rejects_inactive_status_filter(
    client: TestClient,
    admin_session: Session,
):
    admin = create_soldier(admin_session, personal_number="bugapi011d", role="admin")

    resp = client.get(
        "/api/admin/bug-reports/export",
        params={"scope": "filtered", "status": "resolved"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 422


def test_export_bug_reports_does_not_change_report_state(
    client: TestClient,
    admin_session: Session,
):
    admin = create_soldier(admin_session, personal_number="bugapi011e", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi012e")
    _submit(client, reporter, description="read only export item", severity="medium")
    report = admin_session.query(BugReport).filter_by(description="read only export item").one()
    report.status = "in_progress"
    report.updated_at = datetime(2026, 8, 14, 9, 15, tzinfo=timezone.utc)
    report.reporter_last_seen_at = datetime(2026, 8, 14, 9, 10, tzinfo=timezone.utc)
    report.audit_snapshot = [{"action": "submit", "entity_type": "bug_report"}]
    admin_session.flush()
    _create_comment(
        admin_session,
        report_id=report.id,
        author_id=admin.id,
        body="Existing triage note",
    )
    admin_session.commit()
    original_comment_count = admin_session.query(BugReportComment).filter_by(bug_report_id=report.id).count()

    resp = client.get("/api/admin/bug-reports/export", headers=auth_headers(admin))

    assert resp.status_code == 200
    admin_session.expire_all()
    refreshed = admin_session.get(BugReport, report.id)
    assert refreshed is not None
    assert refreshed.status == "in_progress"
    assert refreshed.updated_at == datetime(2026, 8, 14, 9, 15, tzinfo=timezone.utc)
    assert refreshed.reporter_last_seen_at == datetime(2026, 8, 14, 9, 10, tzinfo=timezone.utc)
    assert refreshed.audit_snapshot == [{"action": "submit", "entity_type": "bug_report"}]
    assert admin_session.query(BugReportComment).filter_by(bug_report_id=report.id).count() == original_comment_count


def test_update_bug_report_status_persists(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi013", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi014")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.patch(f"/api/admin/bug-reports/{report_id}", json={"status": "resolved"}, headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"

    admin_session.expire_all()
    assert admin_session.get(BugReport, report_id).status == "resolved"


def test_update_bug_report_status_requires_admin(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugapi015")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.patch(f"/api/admin/bug-reports/{report_id}", json={"status": "resolved"}, headers=auth_headers(reporter))
    assert resp.status_code == 403


def test_get_bug_report_json_returns_mirrored_file(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi016", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi017")
    _submit(client, reporter, description="mirrored description")
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(f"/api/admin/bug-reports/{report_id}/json", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["description"] == "mirrored description"


def test_get_bug_report_json_requires_admin(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugapi018")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(f"/api/admin/bug-reports/{report_id}/json", headers=auth_headers(reporter))
    assert resp.status_code == 403


def test_get_bug_report_screenshot_returns_png_bytes(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi019", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi020")
    _submit(client, reporter, screenshot=_TINY_PNG_B64)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(f"/api/admin/bug-reports/{report_id}/screenshot", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_get_bug_report_screenshot_404_when_none_captured(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi021", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi022")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(f"/api/admin/bug-reports/{report_id}/screenshot", headers=auth_headers(admin))
    assert resp.status_code == 404


def _mirror_payload(reporter, **overrides) -> dict:
    import uuid as uuid_mod
    from datetime import datetime, timezone

    payload = {
        "id": str(uuid_mod.uuid4()),
        "reporter_id": str(reporter.id),
        "description": "imported from json mirror",
        "severity": "medium",
        "route": "/duties",
        "nav_history": [],
        "audit_snapshot": [],
        "user_snapshot": {"full_name": reporter.full_name},
        "has_screenshot": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_import_bug_reports_requires_admin(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugapi023")
    resp = client.post(
        "/api/admin/bug-reports/import",
        files={"files": ("r1.json", b"{}", "application/json")},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 403


def test_import_bug_reports_creates_rows_from_json_mirror(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi024", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi025")
    payload = _mirror_payload(reporter)

    resp = client.post(
        "/api/admin/bug-reports/import",
        files={"files": ("r1.json", json.dumps(payload).encode("utf-8"), "application/json")},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == [{"filename": "r1.json", "status": "imported", "detail": None}]

    row = admin_session.get(BugReport, uuid.UUID(payload["id"]))
    assert row is not None
    assert row.description == "imported from json mirror"
    assert row.severity == "medium"
    assert row.screenshot is None


def test_import_bug_reports_flags_duplicate_and_continues(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi026", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi027")
    payload = _mirror_payload(reporter)

    files = [
        ("files", ("first.json", json.dumps(payload).encode("utf-8"), "application/json")),
        ("files", ("dup.json", json.dumps(payload).encode("utf-8"), "application/json")),
    ]
    resp = client.post("/api/admin/bug-reports/import", files=files, headers=auth_headers(admin))
    assert resp.status_code == 200
    statuses = {r["filename"]: r["status"] for r in resp.json()["results"]}
    assert statuses == {"first.json": "imported", "dup.json": "already_exists"}


def test_import_bug_reports_rejects_invalid_json_but_continues(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi028", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi029")
    good = _mirror_payload(reporter)

    files = [
        ("files", ("bad.json", b"not json at all", "application/json")),
        ("files", ("good.json", json.dumps(good).encode("utf-8"), "application/json")),
    ]
    resp = client.post("/api/admin/bug-reports/import", files=files, headers=auth_headers(admin))
    assert resp.status_code == 200
    statuses = {r["filename"]: r["status"] for r in resp.json()["results"]}
    assert statuses == {"bad.json": "error", "good.json": "imported"}
    assert admin_session.get(BugReport, uuid.UUID(good["id"])) is not None


def test_import_bug_reports_imports_with_null_reporter_for_unknown_reporter(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugapi030", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugapi031")
    payload = _mirror_payload(reporter, reporter_id=str(uuid.uuid4()))

    resp = client.post(
        "/api/admin/bug-reports/import",
        files={"files": ("orphan.json", json.dumps(payload).encode("utf-8"), "application/json")},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result["status"] == "imported"
    imported = admin_session.get(BugReport, uuid.UUID(payload["id"]))
    assert imported is not None
    assert imported.reporter_id is None


def test_submit_bug_report_returns_429_after_daily_cap(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="7900010")
    for i in range(50):
        r = client.post(
            "/api/bug-reports",
            headers=auth_headers(s),
            json={"description": f"bug {i}", "severity": "low", "route": "/x", "nav_history": []},
        )
        assert r.status_code == 201, r.text
    r = client.post(
        "/api/bug-reports",
        headers=auth_headers(s),
        json={"description": "bug 51", "severity": "low", "route": "/x", "nav_history": []},
    )
    assert r.status_code == 429
