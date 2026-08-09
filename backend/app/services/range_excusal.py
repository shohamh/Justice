from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    NotificationType,
    RangeAssignment,
    RangeEvent,
    RangeEventStatus,
    RangeExcusalRequest,
    RangeExcusalStatus,
)
from app.services.notifications import create_notification, notify_duty_managers_in_scope
from app.services.ranges import RangeValidationError


def _range_notification(session: Session, **kwargs):
    from app.db.models import SystemSetting
    setting = session.get(SystemSetting, "mitvachim.enabled")
    if setting is None or setting.value is True:
        return create_notification(session, **kwargs)
    return None


def _load_future_event(session: Session, assignment: RangeAssignment) -> RangeEvent:
    event = session.get(RangeEvent, assignment.range_event_id)
    if event is None:
        raise RangeValidationError("range_event_not_found")
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    if event.date <= date.today():
        raise RangeValidationError("event_not_in_future")
    return event


def _validate_reason(reason: str) -> str:
    value = reason.strip()
    if not value:
        raise RangeValidationError("reason_required")
    return value


def _ensure_no_pending(session: Session, assignment_id: uuid.UUID) -> None:
    existing = session.execute(
        select(RangeExcusalRequest.id).where(
            RangeExcusalRequest.range_assignment_id == assignment_id,
            RangeExcusalRequest.status == RangeExcusalStatus.pending,
        ).limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        raise RangeValidationError("excusal_request_already_pending")

def _recheck_soldier_assignments(session: Session, soldier_id: uuid.UUID) -> None:
    from app.db.models import DutyAssignment as _DutyAssignment
    from app.services.duty_eligibility_watch import recheck_assignments

    affected_ids = session.execute(
        select(_DutyAssignment.id).where(
            _DutyAssignment.soldier_id == soldier_id,
            _DutyAssignment.status == "published",
        )
    ).scalars().all()
    if affected_ids:
        recheck_assignments(session, affected_ids)



def request_primary_excusal(
    session: Session, *, assignment: RangeAssignment, reason: str, requested_by: uuid.UUID,
) -> RangeExcusalRequest:
    _load_future_event(session, assignment)
    if assignment.is_reserve:
        raise RangeValidationError("assignment_is_reserve")
    if requested_by != assignment.soldier_id:
        raise RangeValidationError("not_assignment_owner")
    _ensure_no_pending(session, assignment.id)
    request = RangeExcusalRequest(
        range_assignment_id=assignment.id, range_event_id=assignment.range_event_id, requested_by=requested_by,
        reason=_validate_reason(reason), status=RangeExcusalStatus.pending,
    )
    session.add(request)
    session.flush()
    _recheck_soldier_assignments(session, assignment.soldier_id)
    _range_notification(
        session, soldier_id=assignment.soldier_id, type=NotificationType.range_excusal_pending,
        title="בקשת ההיעדרות נשלחה", reference_type="range_excusal_request",
        reference_id=request.id, actor_id=requested_by,
    )
    session.commit()
    session.refresh(request)
    return request


def request_reserve_excusal(
    session: Session, *, assignment: RangeAssignment, reason: str, requested_by: uuid.UUID,
) -> RangeExcusalRequest:
    _load_future_event(session, assignment)
    if not assignment.is_reserve:
        raise RangeValidationError("assignment_is_primary")
    if requested_by != assignment.soldier_id:
        raise RangeValidationError("not_assignment_owner")
    _ensure_no_pending(session, assignment.id)
    request = RangeExcusalRequest(
        range_assignment_id=assignment.id, range_event_id=assignment.range_event_id, requested_by=requested_by,
        reason=_validate_reason(reason), status=RangeExcusalStatus.approved,
        decided_by=None, decided_at=datetime.now(UTC),
    )
    session.add(request)
    session.delete(assignment)
    session.flush()

    _recheck_soldier_assignments(session, assignment.soldier_id)

    _range_notification(
        session, soldier_id=requested_by, type=NotificationType.range_reserve_excused,
        title="הוסרת ממטווח המילואים", reference_type="range_excusal_request",
        reference_id=request.id, actor_id=requested_by,
    )
    notify_duty_managers_in_scope(
        session, soldier_id=requested_by, type=NotificationType.range_reserve_excused,
        title="חייל מילואים הסיר את עצמו", reference_type="range_excusal_request",
        reference_id=request.id, actor_id=requested_by,
    )
    session.commit()
    session.refresh(request)
    return request


def _eligible_assigned_reserves(session: Session, *, event: RangeEvent) -> list[RangeAssignment]:
    from app.db.models import DutyAssignment, RangeEvent, Soldier
    from app.services.constraints import get_approved_constraint_dates
    from app.services.range_auto_assign import _rank_candidate
    from app.services.range_exemption import is_range_exempt

    rows = session.execute(
        select(RangeAssignment).where(
            RangeAssignment.range_event_id == event.id,
            RangeAssignment.is_reserve.is_(True),
            RangeAssignment.is_draft.is_(False),
        )
    ).scalars().all()
    eligible: list[RangeAssignment] = []
    for assignment in rows:
        soldier = session.get(Soldier, assignment.soldier_id)
        if soldier is None or is_range_exempt(session, soldier=soldier, event_date=event.date):
            continue
        if any(start <= event.date <= end for start, end in get_approved_constraint_dates(session, soldier_id=soldier.id)):
            continue
        if session.execute(
            select(DutyAssignment.id).where(
                DutyAssignment.soldier_id == soldier.id,
                DutyAssignment.start_date <= event.date,
                DutyAssignment.end_date > event.date,
            ).limit(1)
        ).scalar_one_or_none() is not None:
            continue
        if session.execute(
            select(RangeAssignment.id).join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id).where(
                RangeAssignment.soldier_id == soldier.id,
                RangeEvent.date == event.date,
                RangeEvent.id != event.id,
            ).limit(1)
        ).scalar_one_or_none() is not None:
            continue
        eligible.append(assignment)
    return sorted(
        eligible,
        key=lambda assignment: _rank_candidate(
            session, soldier=session.get(Soldier, assignment.soldier_id), event=event,
        )[0],
    )


def decide_primary_excusal(
    session: Session, *, request: RangeExcusalRequest, approve: bool,
    decided_by: uuid.UUID, note: str | None = None,
) -> RangeExcusalRequest:
    if request.status != RangeExcusalStatus.pending:
        raise RangeValidationError("excusal_request_already_decided")
    assignment = session.get(RangeAssignment, request.range_assignment_id)
    if assignment is None or assignment.is_reserve:
        raise RangeValidationError("primary_assignment_not_found")
    event = _load_future_event(session, assignment)
    request.status = RangeExcusalStatus.approved if approve else RangeExcusalStatus.rejected
    request.decided_by = decided_by
    request.decided_at = datetime.now(UTC)
    request.decision_note = note.strip() if note and note.strip() else None
    if not approve:
        session.flush()
        _recheck_soldier_assignments(session, assignment.soldier_id)
        _range_notification(
            session, soldier_id=assignment.soldier_id, type=NotificationType.range_excusal_rejected,
            title="בקשת ההיעדרות נדחתה", body=request.decision_note,
            reference_type="range_excusal_request", reference_id=request.id, actor_id=decided_by,
        )
    else:
        session.delete(assignment)
        reserves = _eligible_assigned_reserves(session, event=event)
        promoted = reserves[0] if reserves else None
        if promoted is not None:
            promoted.is_reserve = False
            request.promoted_assignment_id = promoted.id

        # Both the excused soldier (whose future qualification window from this
        # assignment just disappeared) and, if applicable, the promoted reserve
        # (who just gained one) may have had their weapon eligibility affected.
        affected_soldier_ids = {assignment.soldier_id}
        if promoted is not None:
            affected_soldier_ids.add(promoted.soldier_id)
        for _soldier_id in affected_soldier_ids:
            _recheck_soldier_assignments(session, _soldier_id)

        if promoted is not None:
            _range_notification(
                session, soldier_id=promoted.soldier_id, type=NotificationType.range_reserve_promoted,
                title="קודמת משיבוץ מילואים למטווח", reference_type="range_excusal_request",
                reference_id=request.id, actor_id=decided_by,
            )
        _range_notification(
            session, soldier_id=request.requested_by or assignment.soldier_id,
            type=NotificationType.range_excusal_approved, title="בקשת ההיעדרות אושרה",
            reference_type="range_excusal_request", reference_id=request.id, actor_id=decided_by,
        )
        if promoted is None:
            notify_duty_managers_in_scope(
                session, soldier_id=assignment.soldier_id, type=NotificationType.range_excusal_no_backfill,
                title="אין מילואים זכאים לשיבוץ חלופי", reference_type="range_excusal_request",
                reference_id=request.id, actor_id=decided_by,
            )
    session.commit()
    session.refresh(request)
    return request


def list_pending_excusal_requests(session: Session, *, event: RangeEvent) -> list[RangeExcusalRequest]:
    return list(session.execute(
        select(RangeExcusalRequest)
        .join(RangeAssignment, RangeExcusalRequest.range_assignment_id == RangeAssignment.id)
        .where(RangeAssignment.range_event_id == event.id, RangeExcusalRequest.status == RangeExcusalStatus.pending)
        .order_by(RangeExcusalRequest.requested_at)
    ).scalars().all())
