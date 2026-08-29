from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import _node_in_scope, is_duty_manager, scope_root_ids
from app.db.models import (
    HierarchyNode,
    NotificationType,
    RangeAssignmentRequest,
    RangeAssignmentRequestStatus,
    RangeEvent,
    RangeEventStatus,
    Soldier,
)
from app.services.notifications import create_notification


class RangeAssignmentRequestError(Exception):
    pass


def _soldier_in_proposer_scope(session: Session, *, proposer: Soldier, soldier: Soldier) -> bool:
    if proposer.role == "admin":
        return True
    if not is_duty_manager(session, proposer.id):
        return False
    node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    return _node_in_scope(node, scope_root_ids(session, proposer))


def create_assignment_request(
    session: Session,
    *,
    event: RangeEvent,
    soldier_id: uuid.UUID,
    requested_by: Soldier,
    reason: str,
) -> RangeAssignmentRequest:
    reason = reason.strip()
    if not reason:
        raise RangeAssignmentRequestError("reason_required")
    if event.status != RangeEventStatus.planned:
        raise RangeAssignmentRequestError("event_not_planned")
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise RangeAssignmentRequestError("soldier_not_found")
    if not _soldier_in_proposer_scope(session, proposer=requested_by, soldier=soldier):
        raise RangeAssignmentRequestError("soldier_outside_scope")
    pending = session.execute(
        select(RangeAssignmentRequest.id).where(
            RangeAssignmentRequest.range_event_id == event.id,
            RangeAssignmentRequest.soldier_id == soldier_id,
            RangeAssignmentRequest.status == RangeAssignmentRequestStatus.pending,
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise RangeAssignmentRequestError("request_already_pending")

    request = RangeAssignmentRequest(
        range_event_id=event.id,
        soldier_id=soldier_id,
        requested_by=requested_by.id,
        reason=reason,
        system_reason_code="manual_request",
        system_reason_text="Candidate requires responsible duty manager approval",
    )
    session.add(request)
    session.flush()
    create_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.range_assignment_request_pending,
        title="Range assignment request",
        body="You may be assigned to an upcoming range; it is not official yet.",
        reference_type="range_assignment_request",
        reference_id=request.id,
        actor_id=requested_by.id,
    )
    session.commit()
    session.refresh(request)
    return request
