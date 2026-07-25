from __future__ import annotations

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
