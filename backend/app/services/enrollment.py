from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import ExemptionRequest, HierarchyNode, Soldier, SoldierEnrollmentRequest


class EnrollmentError(Exception):
    pass


def try_activate(
    session: Session,
    enrollment_request_id: uuid.UUID,
) -> None:
    """Move soldier to requested node if commander has approved and no exemptions are pending."""
    req = session.get(SoldierEnrollmentRequest, enrollment_request_id)
    if req is None or req.status != "commander_approved":
        return
    pending = session.execute(
        select(ExemptionRequest).where(
            ExemptionRequest.enrollment_request_id == enrollment_request_id,
            ExemptionRequest.status == "pending",
        )
    ).scalars().all()
    if pending:
        return
    soldier = session.get(Soldier, req.soldier_id)
    if soldier is None:
        raise EnrollmentError("soldier not found for enrollment request")
    soldier.hierarchy_node_id = req.requested_node_id
    req.status = "approved"
    session.flush()


def approve_enrollment(
    session: Session,
    *,
    request_id: uuid.UUID,
    decider_id: uuid.UUID,
    decision_note: str | None,
) -> SoldierEnrollmentRequest:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise EnrollmentError("enrollment request not found")
    if req.status != "pending":
        raise EnrollmentError("already decided")
    req.status = "commander_approved"
    req.decided_by = decider_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_note = decision_note
    session.flush()
    write_audit(session, actor_id=decider_id, action="enrollment.approve",
                entity_type="soldier_enrollment_request", entity_id=req.id,
                after={"soldier_id": str(req.soldier_id), "node_id": str(req.requested_node_id)})
    try_activate(session, req.id)
    return req


def reject_enrollment(
    session: Session,
    *,
    request_id: uuid.UUID,
    decider_id: uuid.UUID,
    decision_note: str,
) -> SoldierEnrollmentRequest:
    req = session.get(SoldierEnrollmentRequest, request_id)
    if req is None:
        raise EnrollmentError("enrollment request not found")
    if req.status != "pending":
        raise EnrollmentError("already decided")
    req.status = "rejected"
    req.decided_by = decider_id
    req.decided_at = datetime.now(timezone.utc)
    req.decision_note = decision_note
    session.flush()
    write_audit(session, actor_id=decider_id, action="enrollment.reject",
                entity_type="soldier_enrollment_request", entity_id=req.id,
                after={"decision_note": decision_note})
    return req


def list_pending_for_node_ids(
    session: Session, node_ids: set[uuid.UUID]
) -> list[SoldierEnrollmentRequest]:
    if not node_ids:
        return []
    all_pending = session.execute(
        select(SoldierEnrollmentRequest).where(SoldierEnrollmentRequest.status == "pending")
    ).scalars().all()
    result = []
    for req in all_pending:
        target = session.get(HierarchyNode, req.requested_node_id)
        if target and any(r in target.path_ids for r in node_ids):
            result.append(req)
    return result
