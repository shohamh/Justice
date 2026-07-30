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
