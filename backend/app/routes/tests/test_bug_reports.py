from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import BugReport
from tests.helpers import auth_headers, create_soldier


def _submit(client: TestClient, reporter, **overrides):
    body = {"description": "x", "severity": "low", "route": "/"}
    body.update(overrides)
    resp = client.post("/api/bug-reports", json=body, headers=auth_headers(reporter))
    assert resp.status_code == 201
    return resp


def test_update_bug_report_status_to_wont_fix(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugstatus001", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugstatus002")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.patch(
        f"/api/admin/bug-reports/{report_id}",
        json={"status": "wont_fix"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "wont_fix"

    admin_session.expire_all()
    assert admin_session.get(BugReport, report_id).status == "wont_fix"


def test_reporter_can_post_comment_on_own_bug_report(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugcomment001")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments",
        json={"body": "steps to reproduce: ..."},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 201
    assert resp.json()["body"] == "steps to reproduce: ..."


def test_other_soldier_cannot_comment_on_someone_elses_bug_report(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugcomment002")
    other = create_soldier(admin_session, personal_number="bugcomment003")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments",
        json={"body": "not mine"},
        headers=auth_headers(other),
    )
    assert resp.status_code == 403


def test_admin_can_comment_on_any_bug_report(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugcomment004", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugcomment005")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments",
        json={"body": "looking into it"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201
