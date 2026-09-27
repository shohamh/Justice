from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, can_view_medical_document, is_duty_manager
from app.db.models import (
    BugReport,
    BugReportComment,
    BugReportCommentAttachment,
    DutyAssignment,
    DutyDismissal,
    ExemptionRequest,
    ExemptionRequestFile,
    GimelimAttachment,
    HierarchyNode,
    ImportSession,
    Soldier,
    SoldierExemption,
    SoldierExemptionFile,
)
from app.storage.keys import make_object_key

MAX_FILE_BYTES = {
    "exemption_request": 25 * 1024 * 1024,
    "soldier_exemption": 25 * 1024 * 1024,
    "gimelim": 10 * 1024 * 1024,
    "bug_report_screenshot": 10 * 1024 * 1024,
    "bug_report_comment": 10 * 1024 * 1024,
    "import_workbook": 25 * 1024 * 1024,
}


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="file_not_found")


def _denied() -> HTTPException:
    return HTTPException(status_code=403, detail="file_download_forbidden")


def _target_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.left_at is not None:
        raise _not_found()
    return soldier


def _metadata(file_class: str, row, object_id: uuid.UUID):
    if row.storage_key != make_object_key(file_class, object_id):
        raise _not_found()
    size, checksum = row.storage_size, row.storage_sha256
    if not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES[file_class]:
        raise _not_found()
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise _not_found()
    content_type = getattr(row, "content_type", None)
    filename = getattr(row, "file_name", None)
    if file_class == "bug_report_screenshot":
        content_type = "image/png"
        filename = filename or f"screenshot-{object_id}.png"
    elif file_class == "import_workbook":
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = getattr(row, "filename", None)
    if not content_type or not filename:
        raise _not_found()
    return {
        "object_key": row.storage_key,
        "sha256": checksum,
        "size": size,
        "content_type": content_type,
        "filename": filename,
    }


def _require_node_action(session: Session, actor: Soldier, target: Soldier, action: str) -> None:
    node = (
        session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
    )
    if node is None:
        raise _denied()
    try:
        authorize(session, actor, action, target_node=node)
    except HTTPException as exc:
        raise _denied() from exc


def authorize_file(session: Session, actor: Soldier, request):
    """Resolve concrete file-parent relationships and recheck live policy on every request."""
    if actor.left_at is not None:
        raise HTTPException(status_code=401, detail="user_not_found")
    if request.kind != "import_workbook" and getattr(actor, "must_change_password", False):
        raise _denied()
    if request.kind == "exemption_request":
        row = session.get(ExemptionRequestFile, request.file_id)
        parent = session.get(ExemptionRequest, request.request_id)
        if row is None or parent is None or row.exemption_request_id != parent.id:
            raise _not_found()
        target = _target_soldier(session, parent.soldier_id)
        if actor.id != target.id and not can_view_medical_document(session, actor, target):
            raise _denied()
        return _metadata("exemption_request", row, row.id)
    if request.kind == "soldier_exemption":
        row = session.get(SoldierExemptionFile, request.file_id)
        parent = session.get(SoldierExemption, request.exemption_id)
        if (
            row is None
            or parent is None
            or row.soldier_exemption_id != parent.id
            or parent.revoked_at is not None
        ):
            raise _not_found()
        target = _target_soldier(session, parent.soldier_id)
        if actor.id != target.id:
            _require_node_action(session, actor, target, Action.EXEMPTION_READ)
        if parent.is_medical and not can_view_medical_document(session, actor, target):
            raise _denied()
        return _metadata("soldier_exemption", row, row.id)
    if request.kind == "gimelim":
        row = session.get(GimelimAttachment, request.attachment_id)
        dismissal = session.get(DutyDismissal, request.dismissal_id)
        if (
            row is None
            or dismissal is None
            or row.dismissal_id != dismissal.id
            or not dismissal.is_gimelim
        ):
            raise _not_found()
        assignment = session.get(DutyAssignment, dismissal.duty_assignment_id)
        if assignment is None:
            raise _not_found()
        target = _target_soldier(session, assignment.soldier_id)
        if actor.id != target.id and actor.role != "admin":
            _require_node_action(session, actor, target, Action.ASSIGNMENT_MANAGE)
        return _metadata("gimelim", row, row.id)
    if request.kind == "bug_report_screenshot":
        report = session.get(BugReport, request.report_id)
        if report is None or not report.storage_key:
            raise _not_found()
        if actor.role != "admin" and actor.id != report.reporter_id:
            raise _denied()
        return _metadata("bug_report_screenshot", report, report.id)
    if request.kind == "bug_report_comment":
        report = session.get(BugReport, request.report_id)
        comment = session.get(BugReportComment, request.comment_id)
        row = session.get(BugReportCommentAttachment, request.attachment_id)
        if (
            report is None
            or comment is None
            or row is None
            or comment.bug_report_id != report.id
            or row.comment_id != comment.id
        ):
            raise _not_found()
        if actor.role != "admin" and actor.id != report.reporter_id:
            raise _denied()
        return _metadata("bug_report_comment", row, row.id)
    if request.kind == "import_workbook":
        row = session.get(ImportSession, request.session_id)
        if row is None or not row.storage_key:
            raise _not_found()
        if actor.role != "admin" and (
            actor.id != row.created_by or not is_duty_manager(session, actor.id)
        ):
            raise _denied()
        return _metadata("import_workbook", row, row.id)
    raise _not_found()
