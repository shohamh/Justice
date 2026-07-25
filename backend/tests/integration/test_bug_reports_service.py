from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models import AuditLog, BugReport
from app.services import bug_reports as svc
from tests.helpers import create_soldier


def test_write_bug_report_persists_row_and_json_mirror(admin_session: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)
    reporter = create_soldier(admin_session, personal_number="bugsvc001")

    result = svc.write_bug_report(
        admin_session,
        reporter=reporter,
        description="the button does nothing",
        severity="medium",
        screenshot=None,
        route="/duty",
        nav_history=[
            {"path": "/", "timestamp": "2026-07-25T10:00:00Z"},
            {"path": "/duty", "timestamp": "2026-07-25T10:00:05Z"},
        ],
    )
    admin_session.commit()

    assert result.persisted_to_db is True
    assert result.json_file_path is not None

    row = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one()
    assert row.description == "the button does nothing"
    assert row.severity == "medium"
    assert row.status == "open"
    assert row.route == "/duty"
    assert row.screenshot is None
    assert row.json_file_path == result.json_file_path

    mirrored = json.loads(Path(result.json_file_path).read_text())
    assert mirrored["description"] == "the button does nothing"
    assert mirrored["user_snapshot"]["id"] == str(reporter.id)


def test_write_bug_report_includes_recent_audit_log_entries(admin_session: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)
    reporter = create_soldier(admin_session, personal_number="bugsvc002")
    admin_session.add(AuditLog(action="login", entity_type="soldier", actor_id=reporter.id, entity_id=reporter.id))
    admin_session.commit()

    svc.write_bug_report(
        admin_session, reporter=reporter, description="x", severity="low", screenshot=None, route="/", nav_history=[],
    )
    admin_session.commit()

    row = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one()
    assert len(row.audit_snapshot) == 1
    assert row.audit_snapshot[0]["action"] == "login"


def test_write_bug_report_stores_screenshot_bytes(admin_session: Session, tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)
    reporter = create_soldier(admin_session, personal_number="bugsvc003")

    svc.write_bug_report(
        admin_session, reporter=reporter, description="x", severity="low",
        screenshot=b"\x89PNG\r\n\x1a\nrest-of-file", route="/", nav_history=[],
    )
    admin_session.commit()

    row = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one()
    assert row.screenshot == b"\x89PNG\r\n\x1a\nrest-of-file"


def test_write_bug_report_returns_success_when_only_db_fails(admin_session: Session, tmp_path, monkeypatch):
    # JSON mirror succeeds (LOG_DIR is a valid tmp dir); the DB insert fails because
    # this reporter was never actually persisted, so the FK constraint violates on
    # flush. Per the spec, this must NOT raise — the JSON file is durable, so the
    # write is still a success from the caller's perspective.
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path)
    from app.db.models import Soldier
    import uuid
    phantom_reporter = Soldier(personal_number="phantom2", full_name="Phantom2", password_hash="x")
    phantom_reporter.id = uuid.uuid4()

    result = svc.write_bug_report(
        admin_session, reporter=phantom_reporter, description="x", severity="low",
        screenshot=None, route="/", nav_history=[],
    )

    assert result.persisted_to_db is False
    assert result.json_file_path is not None
    assert Path(result.json_file_path).exists()


def test_write_bug_report_raises_when_json_write_fails_and_db_fails(admin_session: Session, tmp_path, monkeypatch):
    # Point LOG_DIR at a file (not a directory) so mkdir()/write_text() raise OSError,
    # and break the DB insert by handing it a reporter that was never committed
    # (so the FK constraint fails on flush).
    monkeypatch.setattr(svc, "LOG_DIR", tmp_path / "not-a-dir")
    (tmp_path / "not-a-dir").write_text("blocking file")

    from app.db.models import Soldier
    import uuid
    phantom_reporter = Soldier(
        personal_number="phantom", full_name="Phantom", password_hash="x",
    )
    phantom_reporter.id = uuid.uuid4()

    with pytest.raises(svc.BugReportWriteError):
        svc.write_bug_report(
            admin_session, reporter=phantom_reporter, description="x", severity="low",
            screenshot=None, route="/", nav_history=[],
        )
