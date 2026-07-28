from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import BugReport
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


def test_import_bug_reports_reports_error_for_unknown_reporter(client: TestClient, admin_session: Session):
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
    assert result["status"] == "error"
    assert admin_session.get(BugReport, uuid.UUID(payload["id"])) is None
