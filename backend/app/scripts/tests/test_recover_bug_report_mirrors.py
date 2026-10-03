from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import app.scripts.recover_bug_report_mirrors as recovery
from app.db.models import BugReport
from app.storage.keys import make_object_key
from tests.helpers import create_soldier


class FakeStorage:
    def __init__(self, objects, missing_keys=()):
        self.objects = objects
        self.missing_keys = list(missing_keys)

    def iter_keys(self, *, prefix):
        return [key for key in [*self.objects, *self.missing_keys] if key.startswith(prefix)]

    def open_read(self, *, key):
        import io

        body = self.objects[key]
        return io.BytesIO(body), len(body)


def _payload(report_id, reporter_id, **extra):
    return {
        "id": str(report_id),
        "reporter_id": str(reporter_id),
        "description": "recover me",
        "severity": "low",
        "route": "/",
        "created_at": "2026-09-27T10:00:00+00:00",
        "has_screenshot": False,
        "json_mirror_storage_key": make_object_key("bug_report_json_mirror", report_id),
        "screenshot_storage_key": None,
        "screenshot_storage_sha256": None,
        "screenshot_storage_size": None,
        **extra,
    }


def _wire(monkeypatch, session, storage):
    @contextmanager
    def scope():
        yield session

    monkeypatch.setattr(recovery, "get_settings", lambda: SimpleNamespace(storage_bucket="test-bucket"))
    monkeypatch.setattr(recovery, "S3MaintenanceObjectStorage", lambda _settings: storage)
    monkeypatch.setattr(recovery, "session_scope", scope)


def test_recovery_counts_malformed_and_missing_mirrors_without_crashing(admin_session, monkeypatch, capsys):
    malformed_id = uuid.uuid4()
    missing_id = uuid.uuid4()
    malformed_key = make_object_key("bug_report_json_mirror", malformed_id)
    missing_key = make_object_key("bug_report_json_mirror", missing_id)
    storage = FakeStorage({malformed_key: b"{broken"}, missing_keys=[missing_key])
    _wire(monkeypatch, admin_session, storage)

    assert recovery.main([]) == 1
    counts = json.loads(capsys.readouterr().out)
    assert counts["failed"] == 2
    assert admin_session.query(BugReport).count() == 0


def test_failed_database_commit_leaves_mirror_for_retry(admin_session, monkeypatch, capsys):
    reporter = create_soldier(admin_session, personal_number=f"recover{uuid.uuid4().hex[:8]}")
    report_id = uuid.uuid4()
    key = make_object_key("bug_report_json_mirror", report_id)
    storage = FakeStorage({key: json.dumps(_payload(report_id, reporter.id)).encode()})
    _wire(monkeypatch, admin_session, storage)
    real_commit = admin_session.commit
    failed_once = False

    def fail_first_commit():
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("database unavailable")
        real_commit()

    monkeypatch.setattr(admin_session, "commit", fail_first_commit)
    assert recovery.main([]) == 1
    assert json.loads(capsys.readouterr().out)["failed"] == 1
    assert key in storage.objects
    assert admin_session.query(BugReport).filter_by(id=report_id).one_or_none() is None

    monkeypatch.setattr(admin_session, "commit", real_commit)
    assert recovery.main([]) == 0
    assert json.loads(capsys.readouterr().out)["recovered"] == 1
    assert admin_session.query(BugReport).filter_by(id=report_id).one_or_none() is not None


def test_recovery_rejects_screenshot_object_with_wrong_hash_or_size(admin_session, monkeypatch, capsys):
    reporter = create_soldier(admin_session, personal_number=f"recover{uuid.uuid4().hex[:8]}")
    report_id = uuid.uuid4()
    mirror_key = make_object_key("bug_report_json_mirror", report_id)
    screenshot_key = make_object_key("bug_report_screenshot", report_id)
    expected = b"\x89PNG\r\n\x1a\n" + b"expected"
    wrong = b"\x89PNG\r\n\x1a\n" + b"differs!"
    payload = _payload(
        report_id,
        reporter.id,
        has_screenshot=True,
        screenshot_storage_key=screenshot_key,
        screenshot_storage_sha256=hashlib.sha256(expected).hexdigest(),
        screenshot_storage_size=len(expected),
    )
    storage = FakeStorage({mirror_key: json.dumps(payload).encode(), screenshot_key: wrong})
    _wire(monkeypatch, admin_session, storage)

    assert recovery.main([]) == 1
    assert json.loads(capsys.readouterr().out)["failed"] == 1
    assert admin_session.query(BugReport).filter_by(id=report_id).one_or_none() is None


def test_recovery_imports_screenshot_after_size_and_hash_verification(admin_session, monkeypatch, capsys):
    reporter = create_soldier(admin_session, personal_number=f"recover{uuid.uuid4().hex[:8]}")
    report_id = uuid.uuid4()
    mirror_key = make_object_key("bug_report_json_mirror", report_id)
    screenshot_key = make_object_key("bug_report_screenshot", report_id)
    screenshot = b"\x89PNG\r\n\x1a\n" + b"verified"
    payload = _payload(
        report_id,
        reporter.id,
        has_screenshot=True,
        screenshot_storage_key=screenshot_key,
        screenshot_storage_sha256=hashlib.sha256(screenshot).hexdigest(),
        screenshot_storage_size=len(screenshot),
    )
    storage = FakeStorage({mirror_key: json.dumps(payload).encode(), screenshot_key: screenshot})
    _wire(monkeypatch, admin_session, storage)

    assert recovery.main([]) == 0
    assert json.loads(capsys.readouterr().out)["recovered"] == 1
    report = admin_session.query(BugReport).filter_by(id=report_id).one()
    assert report.storage_key == screenshot_key
    assert report.storage_sha256 == hashlib.sha256(screenshot).hexdigest()
    assert report.storage_size == len(screenshot)
