from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExemptionRequest, ExemptionType, NotificationType, SoldierExemption
from app.services.date_validation import check_max_span
from app.services.exemptions import ExemptionError, grant_commander_exemption
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
    check_max_span(start_date, end_date, ExemptionRequestError)

    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise ExemptionRequestError("exemption_type_not_found")
    if et.is_commander_exemption:
        raise ExemptionRequestError("commander_exemption_not_requestable")

    req = ExemptionRequest(
        soldier_id=soldier_id,
        exemption_type_id=exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status="pending_commander",
    )
    session.add(req)
    session.flush()
    from app.services.notifications import notify_commanders_of_request
    notify_commanders_of_request(
        session,
        soldier_id=soldier_id,
        type=NotificationType.exemption_request_pending,
        title="בקשת פטור חדשה",
        body=reason,
        reference_type="exemption_request",
        reference_id=req.id,
        actor_id=None,
    )
    return req


def submit_commander_escalation(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    official_exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None,
    reason: str | None,
    apply_immediately: bool,
    actor_id: uuid.UUID,
    commander_exemption_type_id: uuid.UUID | None = None,
) -> ExemptionRequest:
    official_type = session.get(ExemptionType, official_exemption_type_id)
    if official_type is None:
        raise ExemptionRequestError("exemption_type_not_found")
    if official_type.is_commander_exemption:
        raise ExemptionRequestError("official_exemption_type_required")
    if apply_immediately and commander_exemption_type_id is None:
        raise ExemptionRequestError("commander_exemption_type_required")
    if end_date is not None and end_date < start_date:
        raise ExemptionRequestError("bad_date_range")
    check_max_span(start_date, end_date, ExemptionRequestError)

    linked_exemption_id = None
    if apply_immediately:
        exemption = grant_commander_exemption(
            session,
            soldier_id=soldier_id,
            exemption_type_id=commander_exemption_type_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            actor_id=actor_id,
        )
        linked_exemption_id = exemption.id

    req = ExemptionRequest(
        soldier_id=soldier_id,
        exemption_type_id=official_exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status="pending_duty_manager",
        commander_approved_by=actor_id,
        linked_commander_exemption_id=linked_exemption_id,
    )
    session.add(req)
    session.flush()

    from app.services.notifications import notify_duty_managers_of_request
    notify_duty_managers_of_request(
        session,
        soldier_id=soldier_id,
        type=NotificationType.exemption_request_pending,
        title="בקשת פטור חדשה (הועלתה ע\"י מפקד)",
        body=reason,
        reference_type="exemption_request",
        reference_id=req.id,
        actor_id=actor_id,
    )
    return req


def list_own_requests(session: Session, soldier_id: uuid.UUID) -> list[ExemptionRequest]:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id == soldier_id
    ).order_by(ExemptionRequest.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def list_pending_requests(session: Session, soldier_ids: list[uuid.UUID]) -> list[ExemptionRequest]:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id.in_(soldier_ids),
        ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
    ).order_by(ExemptionRequest.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def count_pending_requests(session: Session, soldier_ids: list[uuid.UUID]) -> int:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id.in_(soldier_ids),
        ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
    )
    return len(list(session.execute(stmt).scalars().all()))


def approve_commander_step(
    session: Session,
    request_id: uuid.UUID,
    approved_by: uuid.UUID,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status != "pending_commander":
        raise ExemptionRequestError("exemption_request_not_pending_commander")
    req.status = "pending_duty_manager"
    req.commander_approved_by = approved_by
    session.flush()
    return req


def approve_duty_manager_step(
    session: Session,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_note: str | None = None,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status != "pending_duty_manager":
        raise ExemptionRequestError("exemption_request_not_pending_duty_manager")

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
    if req.enrollment_request_id:
        from app.services.enrollment import try_activate
        try_activate(session, req.enrollment_request_id)
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
    if req.status not in ("pending_commander", "pending_duty_manager"):
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
    if req.enrollment_request_id:
        from app.services.enrollment import try_activate
        try_activate(session, req.enrollment_request_id)
    return req
