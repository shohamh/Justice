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
