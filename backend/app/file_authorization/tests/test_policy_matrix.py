import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.file_authorization.policies as policies
from app.auth.authz import Action
from app.db.models import (
    BugReport,
    BugReportComment,
    BugReportCommentAttachment,
    DutyAssignment,
    DutyDismissal,
    GimelimAttachment,
    ImportSession,
    Soldier,
    SoldierExemption,
    SoldierExemptionFile,
)
from app.file_authorization.schemas import (
    BugReportCommentAttachmentRequest,
    BugReportScreenshotRequest,
    GimelimAttachmentRequest,
    ImportWorkbookRequest,
    SoldierExemptionFileRequest,
)
from app.storage.keys import make_object_key


class DB:
    def __init__(self, *rows):
        self.rows = {(kind, key): value for kind, key, value in rows}

    def get(self, kind, key):
        return self.rows.get((kind, key))


def actor(uid=None, role="soldier", **extra):
    return SimpleNamespace(
        id=uid or uuid.uuid4(), role=role, left_at=None, hierarchy_node_id=uuid.uuid4(), **extra
    )


def stored(kind, uid, **fields):
    return SimpleNamespace(
        id=uid,
        storage_key=make_object_key(kind, uid),
        storage_sha256="a" * 64,
        storage_size=7,
        content_type="application/pdf",
        file_name="file.pdf",
        **fields,
    )


def call_denied(db, user, request, status_code):
    with pytest.raises(HTTPException) as exc:
        policies.authorize_file(db, user, request)
    assert exc.value.status_code == status_code


def test_soldier_exemption_self_and_scoped_manager_rules(monkeypatch):
    soldier_id, exemption_id, file_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    self_user = actor(soldier_id)
    target = SimpleNamespace(id=soldier_id, left_at=None, hierarchy_node_id=uuid.uuid4())
    parent = SimpleNamespace(
        id=exemption_id, soldier_id=soldier_id, is_medical=False, revoked_at=None
    )
    row = stored("soldier_exemption", file_id, soldier_exemption_id=exemption_id)
    db = DB(
        (SoldierExemptionFile, file_id, row),
        (SoldierExemption, exemption_id, parent),
        (Soldier, soldier_id, target),
    )
    req = SoldierExemptionFileRequest(
        kind="soldier_exemption", exemption_id=exemption_id, file_id=file_id
    )
    assert (
        policies.authorize_file(db, self_user, req)["object_key"] == f"soldier_exemption/{file_id}"
    )

    manager = actor(role="duty_manager")
    calls = []
    monkeypatch.setattr(
        policies, "_require_node_action", lambda session, user, target, action: calls.append(action)
    )
    monkeypatch.setattr(policies, "can_view_medical_document", lambda *args: True)
    parent.is_medical = True
    assert policies.authorize_file(db, manager, req)["object_key"] == f"soldier_exemption/{file_id}"
    assert calls == [Action.EXEMPTION_READ]


def test_soldier_exemption_revoked_or_medical_permission_missing_denies(monkeypatch):
    exemption_id, file_id, soldier_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    user = actor(soldier_id)
    target = SimpleNamespace(id=soldier_id, left_at=None, hierarchy_node_id=None)
    parent = SimpleNamespace(
        id=exemption_id, soldier_id=soldier_id, is_medical=True, revoked_at=None
    )
    row = stored("soldier_exemption", file_id, soldier_exemption_id=exemption_id)
    db = DB(
        (SoldierExemptionFile, file_id, row),
        (SoldierExemption, exemption_id, parent),
        (Soldier, soldier_id, target),
    )
    req = SoldierExemptionFileRequest(
        kind="soldier_exemption", exemption_id=exemption_id, file_id=file_id
    )
    monkeypatch.setattr(policies, "can_view_medical_document", lambda *args: False)
    call_denied(db, user, req, 403)
    parent.revoked_at = object()
    call_denied(db, user, req, 404)


def test_gimelim_checks_exact_dismissal_and_current_assignment_permission(monkeypatch):
    dismissal_id, attachment_id, assignment_id, soldier_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    target = SimpleNamespace(id=soldier_id, left_at=None, hierarchy_node_id=uuid.uuid4())
    dismissal = SimpleNamespace(id=dismissal_id, duty_assignment_id=assignment_id, is_gimelim=True)
    assignment = SimpleNamespace(id=assignment_id, soldier_id=soldier_id)
    attachment = stored("gimelim", attachment_id, dismissal_id=dismissal_id)
    db = DB(
        (GimelimAttachment, attachment_id, attachment),
        (DutyDismissal, dismissal_id, dismissal),
        (DutyAssignment, assignment_id, assignment),
        (Soldier, soldier_id, target),
    )
    manager = actor(role="duty_manager")
    actions = []
    monkeypatch.setattr(
        policies,
        "_require_node_action",
        lambda session, user, target, action: actions.append(action),
    )
    req = GimelimAttachmentRequest(
        kind="gimelim", dismissal_id=dismissal_id, attachment_id=attachment_id
    )
    assert policies.authorize_file(db, manager, req)["object_key"] == f"gimelim/{attachment_id}"
    assert actions == [Action.ASSIGNMENT_MANAGE]
    mismatch = GimelimAttachmentRequest(
        kind="gimelim", dismissal_id=uuid.uuid4(), attachment_id=attachment_id
    )
    call_denied(db, manager, mismatch, 404)


def test_bug_screenshot_is_reporter_or_admin_only():
    report_id, reporter_id = uuid.uuid4(), uuid.uuid4()
    report = stored("bug_report_screenshot", report_id, reporter_id=reporter_id)
    db = DB((BugReport, report_id, report))
    req = BugReportScreenshotRequest(kind="bug_report_screenshot", report_id=report_id)
    assert policies.authorize_file(db, actor(reporter_id), req)["content_type"] == "image/png"
    assert (
        policies.authorize_file(db, actor(role="admin"), req)["object_key"]
        == f"bug_report_screenshot/{report_id}"
    )
    call_denied(db, actor(), req, 403)


def test_bug_comment_attachment_binds_report_comment_and_attachment():
    report_id, comment_id, attachment_id, reporter_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    report = SimpleNamespace(id=report_id, reporter_id=reporter_id)
    comment = SimpleNamespace(id=comment_id, bug_report_id=report_id)
    attachment = stored("bug_report_comment", attachment_id, comment_id=comment_id)
    db = DB(
        (BugReport, report_id, report),
        (BugReportComment, comment_id, comment),
        (BugReportCommentAttachment, attachment_id, attachment),
    )
    req = BugReportCommentAttachmentRequest(
        kind="bug_report_comment",
        report_id=report_id,
        comment_id=comment_id,
        attachment_id=attachment_id,
    )
    assert (
        policies.authorize_file(db, actor(reporter_id), req)["object_key"]
        == f"bug_report_comment/{attachment_id}"
    )
    bad = BugReportCommentAttachmentRequest(
        kind="bug_report_comment",
        report_id=uuid.uuid4(),
        comment_id=comment_id,
        attachment_id=attachment_id,
    )
    call_denied(db, actor(reporter_id), bad, 404)


def test_import_workbook_requires_creator_still_duty_manager_or_admin(monkeypatch):
    session_id, creator = uuid.uuid4(), uuid.uuid4()
    row = SimpleNamespace(
        id=session_id,
        storage_key=make_object_key("import_workbook", session_id),
        storage_sha256="b" * 64,
        storage_size=12,
        filename="source.xlsx",
        created_by=creator,
    )
    db = DB((ImportSession, session_id, row))
    req = ImportWorkbookRequest(kind="import_workbook", session_id=session_id)
    creator_user = actor(creator, role="duty_manager")
    monkeypatch.setattr(policies, "is_duty_manager", lambda session, uid: True)
    assert policies.authorize_file(db, creator_user, req)["filename"] == "source.xlsx"
    monkeypatch.setattr(policies, "is_duty_manager", lambda session, uid: False)
    call_denied(db, creator_user, req, 403)
    assert (
        policies.authorize_file(db, actor(role="admin"), req)["object_key"]
        == f"import_workbook/{session_id}"
    )
