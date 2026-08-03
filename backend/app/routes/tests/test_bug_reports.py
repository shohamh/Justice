from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import BugReport, BugReportComment, Notification
from app.routes.bug_reports import MAX_ATTACHMENTS_PER_COMMENT, MAX_COMMENTS_PER_REPORT
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


def test_list_bug_report_summaries_include_comment_aggregates(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugsummary001", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugsummary002")
    _submit(client, reporter, description="without comments")
    _submit(client, reporter, description="with comments")
    reports = {
        report.description: report
        for report in admin_session.query(BugReport).filter_by(reporter_id=reporter.id).all()
    }
    older_comment = BugReportComment(
        bug_report_id=reports["with comments"].id,
        author_id=reporter.id,
        body="older comment",
    )
    older_comment.created_at = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    newer_comment = BugReportComment(
        bug_report_id=reports["with comments"].id,
        author_id=reporter.id,
        body="newer comment",
    )
    newer_comment.created_at = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
    admin_comment = BugReportComment(
        bug_report_id=reports["with comments"].id,
        author_id=admin.id,
        body="admin comment",
    )
    admin_comment.created_at = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    admin_session.add_all([older_comment, newer_comment, admin_comment])
    admin_session.commit()

    response = client.get("/api/admin/bug-reports", headers=auth_headers(admin))

    assert response.status_code == 200
    summaries = {item["description"]: item for item in response.json()["items"]}
    assert summaries["without comments"]["comment_count"] == 0
    assert summaries["without comments"]["last_comment_at"] is None
    assert summaries["with comments"]["comment_count"] == 3
    assert datetime.fromisoformat(summaries["with comments"]["last_comment_at"].replace("Z", "+00:00")) == (
        admin_comment.created_at
    )


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


def test_other_soldier_cannot_list_comments_on_someone_elses_bug_report(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugcomment006")
    other = create_soldier(admin_session, personal_number="bugcomment007")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.get(
        f"/api/bug-reports/{report_id}/comments",
        headers=auth_headers(other),
    )
    assert resp.status_code == 403


def test_reporter_and_admin_can_list_comments_on_bug_report(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugcomment008", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugcomment009")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments",
        json={"body": "steps to reproduce: ..."},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 201

    reporter_resp = client.get(
        f"/api/bug-reports/{report_id}/comments",
        headers=auth_headers(reporter),
    )
    assert reporter_resp.status_code == 200
    assert [c["body"] for c in reporter_resp.json()] == ["steps to reproduce: ..."]

    admin_resp = client.get(
        f"/api/bug-reports/{report_id}/comments",
        headers=auth_headers(admin),
    )
    assert admin_resp.status_code == 200
    assert [c["body"] for c in admin_resp.json()] == ["steps to reproduce: ..."]


def test_admin_comment_notifies_bug_report_owner(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="bugnotify001", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugnotify002")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments",
        json={"body": "we are investigating this"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201

    notifications = admin_session.query(Notification).filter_by(soldier_id=reporter.id).all()
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification.title == "תגובה חדשה לדיווח באג"
    assert notification.type.value == "bug_report_comment"
    assert notification.reference_type == "bug_report"
    assert notification.reference_id == report_id


def test_owner_comment_does_not_notify_bug_report_owner(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugnotify003")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments",
        json={"body": "additional details"},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 201
    assert admin_session.query(Notification).filter_by(soldier_id=reporter.id).count() == 0


def _post_comment(client: TestClient, report_id, author, body="a comment"):
    resp = client.post(
        f"/api/bug-reports/{report_id}/comments",
        json={"body": body},
        headers=auth_headers(author),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# Valid PNG: real signature bytes followed by arbitrary payload — enough to pass
# both the declared-content-type check and the magic-byte check.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"rest-of-fake-png-data"


def test_attachment_upload_requires_comment_author_not_just_reporter(client: TestClient, admin_session: Session):
    """The report's own reporter did not author the comment (an admin did) and
    must not be able to attach a file to it — only the comment's author may."""
    admin = create_soldier(admin_session, personal_number="bugattach001", role="admin")
    reporter = create_soldier(admin_session, personal_number="bugattach002")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, admin)

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 403


def test_attachment_upload_rejected_for_unrelated_soldier(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugattach003")
    other = create_soldier(admin_session, personal_number="bugattach004")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, reporter)

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
        headers=auth_headers(other),
    )
    assert resp.status_code == 403


def test_attachment_upload_succeeds_for_comment_author(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugattach005")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, reporter)

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 201
    assert resp.json()["file_name"] == "shot.png"


def test_attachment_upload_rejects_oversized_file(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugattach006")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, reporter)

    oversized = _PNG_BYTES + b"\x00" * (5 * 1024 * 1024)  # well past the 5 MB cap
    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("big.png", oversized, "image/png")},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "file_too_large"


def test_attachment_upload_rejects_disallowed_content_type(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugattach007")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, reporter)

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake pdf body", "application/pdf")},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_file_type"


def test_attachment_upload_rejects_content_not_matching_declared_magic_bytes(
    client: TestClient, admin_session: Session
):
    """Declared content-type is an allowed image type, but the actual bytes
    don't match that type's magic-byte signature — must be rejected, not
    trusted on the declared header alone."""
    reporter = create_soldier(admin_session, personal_number="bugattach008")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, reporter)

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("shot.png", b"this is definitely not a png file", "image/png")},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_file_type"


def _upload_attachment(client: TestClient, report_id, comment_id, author):
    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("shot.png", _PNG_BYTES, "image/png")},
        headers=auth_headers(author),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_download_attachment_succeeds_for_comment_participant(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugattach009")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, reporter)
    attachment_id = _upload_attachment(client, report_id, comment_id, reporter)

    resp = client.get(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments/{attachment_id}",
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 200
    assert resp.content == _PNG_BYTES


def test_download_attachment_404_for_mismatched_report_id(client: TestClient, admin_session: Session):
    """An attachment that really belongs to report A/comment A must not be
    servable by pairing its attachment_id with an unrelated report_id — that
    would be an IDOR leak even if the caller has legitimate access to the
    other report."""
    admin = create_soldier(admin_session, personal_number="bugattach010", role="admin")
    reporter_a = create_soldier(admin_session, personal_number="bugattach011")
    reporter_b = create_soldier(admin_session, personal_number="bugattach012")
    _submit(client, reporter_a)
    _submit(client, reporter_b)
    report_a_id = admin_session.query(BugReport).filter_by(reporter_id=reporter_a.id).one().id
    report_b_id = admin_session.query(BugReport).filter_by(reporter_id=reporter_b.id).one().id
    comment_a_id = _post_comment(client, report_a_id, reporter_a)
    attachment_id = _upload_attachment(client, report_a_id, comment_a_id, reporter_a)

    # admin has access to both reports, but the (report_b_id, comment_a_id) combo is bogus
    resp = client.get(
        f"/api/bug-reports/{report_b_id}/comments/{comment_a_id}/attachments/{attachment_id}",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 404


def test_download_attachment_404_for_mismatched_comment_id(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugattach013")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_1_id = _post_comment(client, report_id, reporter, body="first")
    comment_2_id = _post_comment(client, report_id, reporter, body="second")
    attachment_id = _upload_attachment(client, report_id, comment_1_id, reporter)

    resp = client.get(
        f"/api/bug-reports/{report_id}/comments/{comment_2_id}/attachments/{attachment_id}",
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 404


def test_list_my_bug_reports_scoped_to_own_reports(client: TestClient, admin_session: Session):
    soldier = create_soldier(admin_session, personal_number="bugmine001")
    other = create_soldier(admin_session, personal_number="bugmine002")
    _submit(client, soldier, description="mine")
    _submit(client, other, description="not mine")

    resp = client.get("/api/my/bug-reports", headers=auth_headers(soldier))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["description"] == "mine"
    assert body["items"][0]["reporter_id"] == str(soldier.id)


def test_create_comment_rejected_after_report_hits_comment_cap(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugcap001")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id

    for _ in range(MAX_COMMENTS_PER_REPORT):
        _post_comment(client, report_id, reporter)

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments",
        json={"body": "one too many"},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "too_many_comments"


def test_upload_attachment_rejected_after_comment_hits_attachment_cap(client: TestClient, admin_session: Session):
    reporter = create_soldier(admin_session, personal_number="bugcap002")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, reporter)

    for _ in range(MAX_ATTACHMENTS_PER_COMMENT):
        _upload_attachment(client, report_id, comment_id, reporter)

    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("one_too_many.png", _PNG_BYTES, "image/png")},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "too_many_attachments"


def test_upload_attachment_rejects_oversized_file_without_reading_entire_body(
    client: TestClient, admin_session: Session
):
    """Same external behavior as test_attachment_upload_rejects_oversized_file
    above — this test exists to guard the Step 8 bounded-read refactor from
    accidentally changing the response, not to test something new from
    outside. (The "doesn't buffer the whole body" property is verified by
    code review, not by this test — impractical to measure memory here.)"""
    reporter = create_soldier(admin_session, personal_number="bugcap003")
    _submit(client, reporter)
    report_id = admin_session.query(BugReport).filter_by(reporter_id=reporter.id).one().id
    comment_id = _post_comment(client, report_id, reporter)

    oversized = _PNG_BYTES + b"\x00" * (5 * 1024 * 1024)  # well past the 5 MB cap
    resp = client.post(
        f"/api/bug-reports/{report_id}/comments/{comment_id}/attachments",
        files={"file": ("big.png", oversized, "image/png")},
        headers=auth_headers(reporter),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "file_too_large"
