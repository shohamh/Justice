from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExemptionRequest, ExemptionType, NotificationType, SoldierExemption
from app.services.notifications import create_notification


class ExemptionRequestError(ValueError):
    pass


def submit_request(
    session: Session,
    soldier_id: uuid.UUID,
    exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None = None,
    reason: str | None = None,
) -> ExemptionRequest:
    if end_date and end_date < start_date:
        raise ExemptionRequestError("bad_date_range")

    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise ExemptionRequestError("exemption_type_not_found")

    req = ExemptionRequest(
        soldier_id=soldier_id,
        exemption_type_id=exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status="pending",
    )
    session.add(req)
    session.flush()
    return req


def list_own_requests(session: Session, soldier_id: uuid.UUID) -> list[ExemptionRequest]:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id == soldier_id
    ).order_by(ExemptionRequest.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def list_pending_requests(session: Session, soldier_ids: list[uuid.UUID]) -> list[ExemptionRequest]:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id.in_(soldier_ids),
        ExemptionRequest.status == "pending",
    ).order_by(ExemptionRequest.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def count_pending_requests(session: Session, soldier_ids: list[uuid.UUID]) -> int:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id.in_(soldier_ids),
        ExemptionRequest.status == "pending",
    )
    return len(list(session.execute(stmt).scalars().all()))


def approve_request(
    session: Session,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_note: str | None = None,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status != "pending":
        raise ExemptionRequestError("exemption_request_not_pending")

    req.status = "approved"
    req.decided_by = decided_by
    req.decision_note = decision_note

    exemption = SoldierExemption(
        soldier_id=req.soldier_id,
        exemption_type_id=req.exemption_type_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reason=req.reason,
        granted_by=decided_by,
    )
    session.add(exemption)
    session.flush()
    create_notification(session, soldier_id=req.soldier_id,
                        type=NotificationType.exemption_approved,
                        title="בקשת הפטור אושרה",
                        reference_type="exemption_request", reference_id=req.id,
                        actor_id=decided_by)
    return req


def reject_request(
    session: Session,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_note: str | None = None,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status != "pending":
        raise ExemptionRequestError("exemption_request_not_pending")

    req.status = "rejected"
    req.decided_by = decided_by
    req.decision_note = decision_note
    session.flush()
    create_notification(session, soldier_id=req.soldier_id,
                        type=NotificationType.exemption_rejected,
                        title="בקשת הפטור נדחתה",
                        reference_type="exemption_request", reference_id=req.id,
                        actor_id=decided_by)
    return req
