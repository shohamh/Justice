"""Hierarchy transfer requests: move a soldier to a different hierarchy node,
subject to approval by the destination node's commander/duty managers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyNode, HierarchyTransferRequest, NotificationType, Soldier
from app.services.notifications import create_notification

_DAILY_TRANSFER_REQUEST_LIMIT = 5


class HierarchyTransferError(Exception):
    """Raised on an invalid hierarchy transfer operation."""


def create_request(
    session: Session, *, soldier_id: uuid.UUID, to_node_id: uuid.UUID,
    requested_by: uuid.UUID,
) -> HierarchyTransferRequest:
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise HierarchyTransferError("soldier_not_found")
    if session.get(HierarchyNode, to_node_id) is None:
        raise HierarchyTransferError("to_node_not_found")

    window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_count = session.execute(
        select(func.count()).select_from(HierarchyTransferRequest).where(
            HierarchyTransferRequest.soldier_id == soldier_id,
            HierarchyTransferRequest.created_at >= window_start,
        )
    ).scalar_one()
    if recent_count >= _DAILY_TRANSFER_REQUEST_LIMIT:
        raise HierarchyTransferError("daily_transfer_request_limit_exceeded")

    req = HierarchyTransferRequest(
        soldier_id=soldier_id, from_node_id=soldier.hierarchy_node_id,
        to_node_id=to_node_id, requested_by=requested_by,
    )
    session.add(req)
    session.flush()
    _notify_destination_approvers(session, req)
    write_audit(
        session, actor_id=requested_by, action="hierarchy_transfer.request",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
        after={"soldier_id": str(soldier_id), "to_node_id": str(to_node_id)},
    )
    return req


def _notify_destination_approvers(session: Session, req: HierarchyTransferRequest) -> None:
    from app.db.models import DutyManagerScope, HierarchyNode
    node = session.get(HierarchyNode, req.to_node_id)
    if node is None or not node.path_ids:
        return
    ancestor_ids = node.path_ids
    approver_ids: set[uuid.UUID] = set()
    ancestor_nodes = session.execute(
        select(HierarchyNode).where(HierarchyNode.id.in_(ancestor_ids))
    ).scalars().all()
    for n in ancestor_nodes:
        if n.commander_id:
            approver_ids.add(n.commander_id)
    dm_rows = session.execute(
        select(DutyManagerScope.duty_manager_id).where(
            DutyManagerScope.hierarchy_node_id.in_(ancestor_ids)
        )
    ).scalars().all()
    approver_ids.update(dm_rows)
    for approver_id in approver_ids:
        create_notification(
            session, soldier_id=approver_id, type=NotificationType.transfer_request_pending,
            title="בקשת העברת חייל למסגרת שלך ממתינה לאישור",
            reference_type="hierarchy_transfer_request", reference_id=req.id,
        )


def approve_request(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID,
) -> HierarchyTransferRequest:
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HierarchyTransferError("request_not_found")
    if req.status != "pending":
        raise HierarchyTransferError("not_pending")
    soldier = session.get(Soldier, req.soldier_id)
    old_node_id = soldier.hierarchy_node_id
    soldier.hierarchy_node_id = req.to_node_id
    req.status = "approved"
    req.decided_by = actor_id
    write_audit(
        session, actor_id=actor_id, action="hierarchy_transfer.approve",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
        after={"to_node_id": str(req.to_node_id)},
    )
    from app.services.score_projection import (
        affected_dates_for_soldier_existing_projection,
        refresh_projection_for_change,
    )

    refresh_projection_for_change(
        session,
        soldier_ids={req.soldier_id},
        affected_dates=affected_dates_for_soldier_existing_projection(session, req.soldier_id),
        old_node_ids=({old_node_id} if old_node_id is not None else set()),
        new_node_ids={req.to_node_id},
    )
    return req


def reject_request(
    session: Session, *, request_id: uuid.UUID, actor_id: uuid.UUID, decision_note: str | None = None,
) -> HierarchyTransferRequest:
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HierarchyTransferError("request_not_found")
    if req.status != "pending":
        raise HierarchyTransferError("not_pending")
    req.status = "rejected"
    req.decided_by = actor_id
    req.decision_note = decision_note
    create_notification(
        session, soldier_id=req.requested_by, type=NotificationType.transfer_request_rejected,
        title="בקשת העברת החייל נדחתה", reference_type="hierarchy_transfer_request",
        reference_id=req.id, actor_id=actor_id,
    )
    write_audit(
        session, actor_id=actor_id, action="hierarchy_transfer.reject",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
        after={"decision_note": decision_note},
    )
    return req


def list_pending_for_approver(session: Session, *, approver_id: uuid.UUID) -> list[HierarchyTransferRequest]:
    from app.auth.authz import commanded_node_ids, dm_scope_node_ids
    root_ids = commanded_node_ids(session, approver_id) | dm_scope_node_ids(session, approver_id)
    if not root_ids:
        return []
    pending = list(session.execute(
        select(HierarchyTransferRequest).where(HierarchyTransferRequest.status == "pending")
    ).scalars())
    if not pending:
        return []
    to_node_ids = {r.to_node_id for r in pending}
    nodes_by_id = {
        n.id: n
        for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(to_node_ids))
        ).scalars().all()
    }
    return [
        r for r in pending
        if (node := nodes_by_id.get(r.to_node_id)) is not None
        and any(root_id in node.path_ids for root_id in root_ids)
    ]
