from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.audit.writer import write_audit
from app.auth.authz import scope_root_ids
from app.db.models import (
    HierarchyNode,
    Notification,
    NotificationType,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeEventStatus,
    RangeLocation,
    RangeType,
    ScoreAdjustment,
    Soldier,
    SoldierRangeQualification,
)
from app.services.adjustments import create_adjustment
from app.services.approval_scope import commander_chain_for_soldier
from app.services.notifications import create_notification, notify_duty_managers_in_scope
from app.services.range_exemption import is_range_exempt
from app.services.settings_loader import SettingNotFound, get_setting

if TYPE_CHECKING:  # range_reconciliation imports this module at module scope
    from app.services.range_reconciliation import ReconciliationResult


class RangeValidationError(Exception):
    pass

_UNSET = object()


def _mitvachim_enabled(session: Session) -> bool:
    setting = session.get(__import__("app.db.models", fromlist=["SystemSetting"]).SystemSetting, "mitvachim.enabled")
    return setting is None or setting.value is True


def _range_notification(session: Session, **kwargs):
    if _mitvachim_enabled(session):
        return create_notification(session, **kwargs)
    return None


_RANGE_ASSIGNMENT_LOCK_NAMESPACE = 0x52414E47


def _acquire_range_assignment_date_lock(session: Session, *, event_date: date) -> None:
    session.execute(
        select(
            func.pg_advisory_xact_lock(
                _RANGE_ASSIGNMENT_LOCK_NAMESPACE,
                event_date.toordinal(),
            )
        )
    )



_RANGE_TYPE_HE: dict[RangeType, str] = {
    RangeType.laser: "מטווח לייזר",
    RangeType.live: "מטווח חי",
    RangeType.alal: 'אל"ל',
}


def _range_assignment_body(event: RangeEvent) -> str:
    return f"{_RANGE_TYPE_HE.get(event.range_type, event.range_type.value)} · {event.date.strftime('%d.%m.%Y')}"


def _notify_refilled_assignments(session: Session, reconciliation: ReconciliationResult) -> None:
    """Tell every soldier auto-refilled into a slot vacated by reconciliation that
    they are now assigned, using the same notification a directly created
    assignment gets. Each refill lives on its own (later) event, so the body and
    reference are taken from that assignment's event, not the source event.
    The vacated-slot roster notification is already sent by the removal itself."""
    for assignment_id in (
        reconciliation.refilled_primary_assignment_ids
        + reconciliation.refilled_reserve_assignment_ids
    ):
        assignment = session.get(RangeAssignment, assignment_id)
        refilled_event = session.get(RangeEvent, assignment.range_event_id)
        _range_notification(
            session,
            soldier_id=assignment.soldier_id,
            type=NotificationType.range_assignment_confirmed,
            title="שובצת למטווח",
            body=_range_assignment_body(refilled_event),
            reference_type="range_event",
            reference_id=refilled_event.id,
        )


def _range_context(session: Session, event: RangeEvent, *, reason: str | None = None) -> str:
    from app.db.models import RangeLocation
    loc = session.get(RangeLocation, event.range_location_id)
    location_name = loc.name if loc else str(event.range_location_id)
    context = f"date={event.date.isoformat()} | type={event.range_type.value} | location={location_name}"
    return f"{context} | reason={reason}" if reason else context


def _notify_roster_change(
    session: Session, *, event: RangeEvent, soldier_ids: set[uuid.UUID], actor_id: uuid.UUID | None = None,
) -> None:
    assignments = session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    fill = (
        f"primary={sum(1 for a in assignments if not a.is_reserve and not a.is_draft)}/{event.required_count}"
        f" | reserve={sum(1 for a in assignments if a.is_reserve and not a.is_draft)}/{event.reserve_count}"
    )
    for soldier_id in soldier_ids:
        _range_notification(
            session, soldier_id=soldier_id, type=NotificationType.range_roster_changed,
            title="Range roster changed", body=f"{_range_context(session, event)} | {fill}",
            reference_type="range_event", reference_id=event.id, actor_id=actor_id,
        )
    if soldier_ids and _mitvachim_enabled(session):
        notify_duty_managers_in_scope(session, soldier_id=next(iter(soldier_ids)), type=NotificationType.range_roster_changed, title="Range roster changed", body=f"{_range_context(session, event)} | {fill}", reference_type="range_event", reference_id=event.id, actor_id=actor_id)

def create_range_event(
    session: Session,
    *,
    hierarchy_node_id: uuid.UUID,
    range_type: RangeType,
    event_date: date,
    range_location_id: uuid.UUID,
    required_count: int,
    reserve_count: int = 0,
    start_time: str | None = None,
    end_time: str | None = None,
    arrival_instructions: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> RangeEvent:
    if session.get(HierarchyNode, hierarchy_node_id) is None:
        raise RangeValidationError("hierarchy_node_not_found")
    if session.get(RangeLocation, range_location_id) is None:
        raise RangeValidationError("range_location_not_found")
    if required_count < 0 or reserve_count < 0:
        raise RangeValidationError("counts_must_be_non_negative")
    if start_time and end_time and start_time > end_time:
        raise RangeValidationError("start_time_after_end_time")

    event = RangeEvent(
        hierarchy_node_id=hierarchy_node_id,
        range_type=range_type,
        date=event_date,
        range_location_id=range_location_id,
        required_count=required_count,
        reserve_count=reserve_count,
        start_time=start_time,
        end_time=end_time,
        arrival_instructions=arrival_instructions,
        contact_name=contact_name,
        contact_phone=contact_phone,
        notes=notes,
        created_by=created_by,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def update_range_event(
    session: Session,
    *,
    event: RangeEvent,
    hierarchy_node_id: uuid.UUID | object = _UNSET,
    range_type: RangeType | object = _UNSET,
    event_date: date | object = _UNSET,
    start_time: str | None | object = _UNSET,
    end_time: str | None | object = _UNSET,
    range_location_id: uuid.UUID | object = _UNSET,
    arrival_instructions: str | None | object = _UNSET,
    contact_name: str | None | object = _UNSET,
    contact_phone: str | None | object = _UNSET,
    required_count: int | object = _UNSET,
    reserve_count: int | object = _UNSET,
    notes: str | None | object = _UNSET,
    force_schedule_change: bool = False,
    actor_id: uuid.UUID | None = None,
) -> RangeEvent:
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    assignments_exist = session.query(RangeAssignment.id).filter(
        RangeAssignment.range_event_id == event.id,
        RangeAssignment.is_draft.is_(False),
    ).first() is not None
    schedule_changed = (
        (range_type is not _UNSET and range_type != event.range_type)
        or (event_date is not _UNSET and event_date != event.date)
    )
    if schedule_changed and assignments_exist and not force_schedule_change:
        raise RangeValidationError("schedule_change_confirmation_required")
    proposed_start = event.start_time if start_time is _UNSET else start_time
    proposed_end = event.end_time if end_time is _UNSET else end_time
    if proposed_start and proposed_end and proposed_start > proposed_end:
        raise RangeValidationError("start_time_after_end_time")
    before: dict = {}
    after: dict = {}
    if hierarchy_node_id is not _UNSET:
        if session.get(HierarchyNode, hierarchy_node_id) is None:
            raise RangeValidationError("hierarchy_node_not_found")
        before["hierarchy_node_id"] = str(event.hierarchy_node_id)
        event.hierarchy_node_id = hierarchy_node_id
        after["hierarchy_node_id"] = str(hierarchy_node_id)
    if range_type is not _UNSET:
        before["range_type"] = event.range_type
        event.range_type = range_type
        after["range_type"] = range_type
    if event_date is not _UNSET:
        before["date"] = event.date.isoformat()
        event.date = event_date
        after["date"] = event_date.isoformat()
    if start_time is not _UNSET:
        before["start_time"] = event.start_time
        event.start_time = start_time
        after["start_time"] = start_time
    if end_time is not _UNSET:
        before["end_time"] = event.end_time
        event.end_time = end_time
        after["end_time"] = end_time
    if required_count is not _UNSET:
        if required_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        before["required_count"] = event.required_count
        event.required_count = required_count
        after["required_count"] = required_count
    if reserve_count is not _UNSET:
        if reserve_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        before["reserve_count"] = event.reserve_count
        event.reserve_count = reserve_count
        after["reserve_count"] = reserve_count
    if range_location_id is not _UNSET:
        if session.get(RangeLocation, range_location_id) is None:
            raise RangeValidationError("range_location_not_found")
        before["range_location_id"] = str(event.range_location_id)
        event.range_location_id = range_location_id
        after["range_location_id"] = str(range_location_id)
    if arrival_instructions is not _UNSET:
        before["arrival_instructions"] = event.arrival_instructions
        event.arrival_instructions = arrival_instructions
        after["arrival_instructions"] = arrival_instructions
    if contact_name is not _UNSET:
        before["contact_name"] = event.contact_name
        event.contact_name = contact_name
        after["contact_name"] = contact_name
    if contact_phone is not _UNSET:
        before["contact_phone"] = event.contact_phone
        event.contact_phone = contact_phone
        after["contact_phone"] = contact_phone
    if notes is not _UNSET:
        before["notes"] = event.notes
        event.notes = notes
        after["notes"] = notes
    write_audit(
        session, actor_id=actor_id, action="range_event.update", entity_type="range_event",
        entity_id=event.id, before=before, after=after,
    )
    session.commit()
    session.refresh(event)
    return event


def cancel_range_event(
    session: Session, *, event: RangeEvent, reason: str = "Cancelled", actor_id: uuid.UUID | None = None
) -> RangeEvent:
    reason = reason.strip()
    if not reason:
        raise RangeValidationError("reason_required")
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    previous_status = event.status
    event.cancellation_reason = reason
    event.status = RangeEventStatus.cancelled
    context = _range_context(session, event, reason=reason)
    assignments = session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == event.id
    )).scalars().all()
    for assignment in assignments:
        _range_notification(
            session, soldier_id=assignment.soldier_id, type=NotificationType.range_cancelled,
            title="Range cancelled", body=context, reference_type="range_event",
            reference_id=event.id, actor_id=actor_id,
        )
    if assignments and _mitvachim_enabled(session):
        notify_duty_managers_in_scope(session, soldier_id=assignments[0].soldier_id, type=NotificationType.range_cancelled, title="Range cancelled", body=context, reference_type="range_event", reference_id=event.id, actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="range_event.cancel", entity_type="range_event",
        entity_id=event.id, before={"status": previous_status}, after={"status": event.status},
    )
    session.commit()
    session.refresh(event)
    return event


def mark_past_range_events_completed(session: Session, *, today: date | None = None) -> int:
    today = today or date.today()
    event_ids = session.execute(
        update(RangeEvent)
        .where(
            RangeEvent.status == RangeEventStatus.planned,
            RangeEvent.date < today,
        )
        .values(status=RangeEventStatus.completed)
        .returning(RangeEvent.id)
        .execution_options(synchronize_session="fetch")
    ).scalars().all()
    for event_id in event_ids:
        write_audit(
            session,
            actor_id=None,
            action="range_event.complete",
            entity_type="range_event",
            entity_id=event_id,
            before={"status": RangeEventStatus.planned},
            after={"status": RangeEventStatus.completed},
        )
    session.flush()
    return len(event_ids)


def delete_range_event(session: Session, *, event: RangeEvent) -> None:
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    has_assignments = session.query(RangeAssignment.id).filter(
        RangeAssignment.range_event_id == event.id
    ).first()
    if has_assignments is not None:
        raise RangeValidationError("event_has_assignments")
    has_history = session.query(SoldierRangeQualification.id).filter(
        (SoldierRangeQualification.source_range_event_id == event.id)
        | SoldierRangeQualification.source_range_assignment_id.in_(
            select(RangeAssignment.id).where(RangeAssignment.range_event_id == event.id)
        )
    ).first()
    if has_history is not None:
        raise RangeValidationError("event_has_history")
    session.delete(event)
    session.commit()


def _soldier_in_authorized_scope(session: Session, *, node: HierarchyNode, user: Soldier | None) -> bool:
    """True if `node` falls under the requesting user's commander/duty-manager
    scope. Mirrors range_auto_assign._soldier_pool's widened scope, so a candidate
    the panel legitimately offered (e.g. from a sibling sub-unit under the user's
    broader command) doesn't turn around and get rejected here as "outside the
    event's subunit". user=None (no caller context, e.g. internal/test callers)
    means this check is skipped entirely."""
    if user is None or user.role == "admin":
        return user is not None
    roots = scope_root_ids(session, user)
    return any(root in node.path_ids for root in roots)


def _validate_and_build_assignment(
    session: Session, *, event: RangeEvent, soldier_id: uuid.UUID, is_reserve: bool,
    user: Soldier | None = None, override_reason: str | None = None,
) -> tuple[RangeAssignment, "PersonalConstraint | None"]:
    """Same validation as add_range_assignment (subtree membership, exemption,
    same-date conflict, personal constraint) but only constructs the row — does
    not add/commit/notify. Shared by add_range_assignment (single, notifies) and
    assign_batch (many, one commit + one notification pass at the end). Returns
    the built assignment plus the PersonalConstraint it overrode, if any — callers
    use the second element to decide whether to write an audit row and notify."""
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise RangeValidationError("soldier_not_found")
    node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    event_node = session.get(HierarchyNode, event.hierarchy_node_id)
    if node is None or event_node is None:
        raise RangeValidationError("soldier_outside_event_subunit")
    in_event_subtree = event.hierarchy_node_id in node.path_ids
    if not in_event_subtree and not _soldier_in_authorized_scope(session, node=node, user=user):
        raise RangeValidationError("soldier_outside_event_subunit")
    if is_range_exempt(session, soldier=soldier, event_date=event.date):
        raise RangeValidationError("soldier_range_exempt")
    existing_same_date = session.execute(
        select(RangeAssignment.id)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier_id,
            RangeEvent.date == event.date,
        )
        .limit(1)
    ).scalar_one_or_none()
    if existing_same_date is not None:
        raise RangeValidationError("soldier_already_assigned_on_date")

    from app.db.models import PersonalConstraint
    from app.services.constraint_override_settings import manual_override_allowed

    constraint = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status == "approved",
            PersonalConstraint.start_date <= event.date,
            PersonalConstraint.end_date >= event.date,
        )
    ).scalars().first()
    if constraint is not None:
        if not manual_override_allowed(session):
            raise RangeValidationError("personal_constraint_blocked")
        if not override_reason or not override_reason.strip():
            raise RangeValidationError("override_reason_required")

    return RangeAssignment(range_event_id=event.id, soldier_id=soldier_id, is_reserve=is_reserve), constraint


def _check_capacity(session: Session, *, event: RangeEvent, new_primary: int, new_reserve: int) -> None:
    counts = session.execute(
        select(RangeAssignment.is_reserve, func.count())
        .where(RangeAssignment.range_event_id == event.id)
        .group_by(RangeAssignment.is_reserve)
    ).all()
    existing_primary = next((c for is_res, c in counts if not is_res), 0)
    existing_reserve = next((c for is_res, c in counts if is_res), 0)
    if existing_primary + new_primary > event.required_count:
        raise RangeValidationError("primary_capacity_exceeded")
    if existing_reserve + new_reserve > event.reserve_count:
        raise RangeValidationError("reserve_capacity_exceeded")


def add_range_assignment(
    session: Session, *, event: RangeEvent, soldier_id: uuid.UUID, is_reserve: bool,
    assignment_reason_code: str = "manual", assignment_reason_text: str | None = "שיבוץ ידני",
    user: Soldier | None = None, override_reason: str | None = None,
) -> RangeAssignment:
    _acquire_range_assignment_date_lock(session, event_date=event.date)
    session.refresh(event)
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    _check_capacity(
        session, event=event,
        new_primary=0 if is_reserve else 1,
        new_reserve=1 if is_reserve else 0,
    )
    assignment, overridden_constraint = _validate_and_build_assignment(
        session, event=event, soldier_id=soldier_id, is_reserve=is_reserve, user=user,
        override_reason=override_reason,
    )

    existing_soldier_ids = set(session.execute(select(RangeAssignment.soldier_id).where(
        RangeAssignment.range_event_id == event.id,
    )).scalars())
    assignment.assignment_reason_code = assignment_reason_code
    assignment.assignment_reason_text = assignment_reason_text
    session.add(assignment)
    session.flush()
    if overridden_constraint is not None:
        from app.db.models import PersonalConstraintOverride
        session.add(PersonalConstraintOverride(
            personal_constraint_id=overridden_constraint.id,
            soldier_id=soldier_id,
            overridden_by=user.id if user else None,
            assignment_kind="range",
            reference_id=assignment.id,
            reason=override_reason.strip(),
        ))
        from app.services.notifications import notify_personal_constraint_overridden
        notify_personal_constraint_overridden(
            session, soldier_id=soldier_id, assignment_kind="range",
            reason=override_reason.strip(), actor_id=user.id if user else None,
        )
    # Deferred: range_reconciliation imports this module at module scope.
    from app.services.range_reconciliation import reconcile_future_range_assignments

    reconciliation = reconcile_future_range_assignments(
        session, soldier_id=soldier_id, source_event=event, actor_id=user.id if user else None,
    )
    _notify_roster_change(session, event=event, soldier_ids=existing_soldier_ids)
    _range_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.range_assignment_confirmed,
        title="שובצת למטווח",
        body=_range_assignment_body(event),
        reference_type="range_event",
        reference_id=event.id,
    )
    _notify_refilled_assignments(session, reconciliation)
    session.commit()
    session.refresh(assignment)
    return assignment


def assign_batch(
    session: Session, *, event: RangeEvent,
    primary_soldier_ids: list[uuid.UUID], reserve_soldier_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None, user: Soldier | None = None,
    override_reason: str | None = None,
) -> list[RangeAssignment]:
    """All-or-nothing: validates every soldier before adding any row, so a single
    invalid soldier in the batch fails the whole call with no partial writes.
    Deliberately simpler than shifts' assignBatch (which is partial-success/lenient) —
    the range candidate panel already is the review step, so failing fast on the
    first invalid soldier keeps this endpoint's contract simple."""
    _acquire_range_assignment_date_lock(session, event_date=event.date)
    session.refresh(event)
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    _check_capacity(
        session, event=event,
        new_primary=len(primary_soldier_ids),
        new_reserve=len(reserve_soldier_ids),
    )

    from app.services.range_auto_assign import _rank_candidate

    rows_with_constraints = [
        _validate_and_build_assignment(
            session, event=event, soldier_id=sid, is_reserve=False, user=user,
            override_reason=override_reason,
        )
        for sid in primary_soldier_ids
    ] + [
        _validate_and_build_assignment(
            session, event=event, soldier_id=sid, is_reserve=True, user=user,
            override_reason=override_reason,
        )
        for sid in reserve_soldier_ids
    ]
    for row, _constraint in rows_with_constraints:
        soldier = session.get(Soldier, row.soldier_id)
        _, reason_code, _explanation = _rank_candidate(session, soldier=soldier, event=event)
        row.assignment_reason_code = reason_code
        session.add(row)
    session.flush()
    from app.db.models import PersonalConstraintOverride
    from app.services.notifications import notify_personal_constraint_overridden

    # Deferred: range_reconciliation imports this module at module scope.
    from app.services.range_reconciliation import reconcile_future_range_assignments

    for row, _constraint in rows_with_constraints:
        reconciliation = reconcile_future_range_assignments(
            session, soldier_id=row.soldier_id, source_event=event,
            actor_id=user.id if user else None,
        )
        _notify_refilled_assignments(session, reconciliation)

    for row, constraint in rows_with_constraints:
        _range_notification(
            session, soldier_id=row.soldier_id, type=NotificationType.range_assignment_confirmed,
            title="שובצת למטווח", body=_range_assignment_body(event),
            reference_type="range_event", reference_id=event.id,
        )
        if constraint is not None:
            session.add(PersonalConstraintOverride(
                personal_constraint_id=constraint.id,
                soldier_id=row.soldier_id,
                overridden_by=user.id if user else None,
                assignment_kind="range",
                reference_id=row.id,
                reason=override_reason.strip(),
            ))
            notify_personal_constraint_overridden(
                session, soldier_id=row.soldier_id, assignment_kind="range",
                reason=override_reason.strip(), actor_id=user.id if user else None,
            )
    session.commit()
    rows = [row for row, _constraint in rows_with_constraints]
    for row in rows:
        session.refresh(row)
    return rows


def _remove_range_assignment_in_transaction(
    session: Session, *, assignment: RangeAssignment, reason: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    event = session.get(RangeEvent, assignment.range_event_id)
    if event is not None and event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    remaining_ids = set(session.execute(select(RangeAssignment.soldier_id).where(
        RangeAssignment.range_event_id == assignment.range_event_id,
        RangeAssignment.id != assignment.id,
    )).scalars())
    soldier_id = assignment.soldier_id
    write_audit(
        session, actor_id=actor_id, action="range_assignment.remove", entity_type="range_assignment",
        entity_id=assignment.id,
        before={
            "soldier_id": str(soldier_id),
            "range_event_id": str(assignment.range_event_id),
            "is_reserve": assignment.is_reserve,
        },
        context={"reason": reason},
    )
    session.delete(assignment)
    session.flush()
    _notify_roster_change(
        session, event=event, soldier_ids=remaining_ids | {soldier_id}, actor_id=actor_id,
    )


def remove_range_assignment(
    session: Session, *, assignment: RangeAssignment, reason: str, actor_id: uuid.UUID | None = None,
) -> None:
    _remove_range_assignment_in_transaction(
        session, assignment=assignment, reason=reason, actor_id=actor_id,
    )
    session.commit()


_VALIDITY_SETTING_KEYS: dict[str, str] = {
    RangeType.laser: "mitvachim.laser_validity_days",
    RangeType.live: "mitvachim.live_validity_days",
    RangeType.alal: "mitvachim.alal_validity_days",
}
_NO_SHOW_PENALTY = Decimal("-1")

# Fallback defaults if the corresponding setting row is missing, matching the
# defaults seeded by the add_ranges_tables migration.
_FALLBACK_VALIDITY_DAYS: dict[str, int] = {
    RangeType.laser: 180,
    RangeType.live: 365,
    RangeType.alal: 365,
}


def _validity_days(session: Session, range_type: str) -> int:
    key = _VALIDITY_SETTING_KEYS[range_type]
    try:
        value = get_setting(session, key)
    except SettingNotFound:
        return _FALLBACK_VALIDITY_DAYS[range_type]
    return int(value)


def _record_qualification(session: Session, *, soldier_id: uuid.UUID, range_type: str, valid_until: date,
                           source_range_assignment_id: uuid.UUID) -> None:
    session.add(SoldierRangeQualification(
        soldier_id=soldier_id, range_type=range_type, valid_until=valid_until,
        source_range_assignment_id=source_range_assignment_id,
        source_range_event_id=session.get(RangeAssignment, source_range_assignment_id).range_event_id,
    ))


def get_effective_range_qualification(session: Session, *, soldier_id: uuid.UUID, range_type: str) -> date | None:
    """Returns the soldier's current valid_until for range_type (the furthest-out
    valid_until among all non-deleted qualification rows for that soldier/type), or
    None if they have no qualification record at that type."""
    qualification = aliased(SoldierRangeQualification)
    assignment = aliased(RangeAssignment)
    return session.execute(
        select(func.max(qualification.valid_until))
        .outerjoin(assignment, qualification.source_range_assignment_id == assignment.id)
        .where(
            qualification.soldier_id == soldier_id,
            qualification.range_type == range_type,
            or_(qualification.source_range_assignment_id.is_(None), assignment.attendance_status == RangeAttendanceStatus.present),
        )
    ).scalar_one_or_none()


def _delete_qualification_from_this_assignment(session: Session, *, assignment: RangeAssignment) -> None:
    session.execute(delete(SoldierRangeQualification).where(
        SoldierRangeQualification.source_range_assignment_id == assignment.id,
    ))


def _direct_commander_id(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = commander_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None


_MITVAHIM_RANGE_TYPES = (RangeType.laser, RangeType.live)


def _profile_date_field_for_range_type(range_type: str) -> str:
    return "last_alal_date" if range_type == RangeType.alal else "last_mitvahim_date"


def _sync_profile_date_on_present(soldier: Soldier, *, range_type: str, event_date: date) -> None:
    field = _profile_date_field_for_range_type(range_type)
    current = getattr(soldier, field)
    if current is None or event_date > current:
        setattr(soldier, field, event_date)


def _resync_profile_date_on_reversal(
    session: Session, *, soldier: Soldier, assignment: RangeAssignment, range_type: str, event_date: date,
) -> None:
    field = _profile_date_field_for_range_type(range_type)
    current = getattr(soldier, field)
    if current is not None and current != event_date:
        return  # the stored value didn't come from this attendance -- leave it
    types = (RangeType.alal,) if range_type == RangeType.alal else _MITVAHIM_RANGE_TYPES
    latest = session.execute(
        select(func.max(RangeEvent.date))
        .join(RangeAssignment, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier.id,
            RangeAssignment.attendance_status == RangeAttendanceStatus.present,
            RangeEvent.range_type.in_(types),
            RangeAssignment.id != assignment.id,
        )
    ).scalar_one_or_none()
    if latest is not None:
        setattr(soldier, field, latest)


def mark_attendance(
    session: Session, *, assignment: RangeAssignment, status: RangeAttendanceStatus,
    marked_by: uuid.UUID | None = None, note: str | None = None,
) -> RangeAssignment:
    if assignment.is_draft:
        raise RangeValidationError("assignment_not_confirmed")
    event = session.get(RangeEvent, assignment.range_event_id)
    if event is None:
        raise RangeValidationError("event_not_found")
    if event.status == RangeEventStatus.cancelled:
        raise RangeValidationError("event_cancelled")
    if event.date > date.today():
        raise RangeValidationError("event_not_yet_occurred")

    soldier = session.get(Soldier, assignment.soldier_id)
    previous_status = assignment.attendance_status
    note_required = status == RangeAttendanceStatus.no_show or (
        previous_status != RangeAttendanceStatus.pending and status != previous_status
    )
    if note_required and not note:
        raise RangeValidationError("note_required_for_attendance_change")

    if previous_status == status:
        if status == RangeAttendanceStatus.no_show and _mitvachim_enabled(session):
            latest_body = f"{_range_context(session, event, reason=note)} | assignment={assignment.id}"
            session.query(Notification).filter(
                Notification.type == NotificationType.range_no_show,
                Notification.reference_type == "range_event",
                Notification.reference_id == event.id,
            ).update({Notification.body: latest_body}, synchronize_session=False)
        session.commit()
        session.refresh(assignment)
        return assignment
    no_show_transition = previous_status != RangeAttendanceStatus.no_show and status == RangeAttendanceStatus.no_show
    present_correction = previous_status == RangeAttendanceStatus.no_show and status == RangeAttendanceStatus.present

    # Reverse the previous side effect, if any.
    if previous_status == RangeAttendanceStatus.no_show and assignment.score_adjustment_id is not None:
        original = session.get(ScoreAdjustment, assignment.score_adjustment_id)
        reversal_delta = -original.delta if original is not None else -_NO_SHOW_PENALTY
        create_adjustment(
            session, soldier_id=assignment.soldier_id, delta=reversal_delta,
            reason="range_no_show_reversed", actor_id=marked_by,
        )
        write_audit(
            session, actor_id=marked_by, action="range_attendance_correction_reverse_no_show",
            entity_type="range_assignment", entity_id=assignment.id,
            before={"attendance_status": previous_status}, after=None,
        )
        assignment.score_adjustment_id = None
    if previous_status == RangeAttendanceStatus.present:
        _delete_qualification_from_this_assignment(session, assignment=assignment)
        _resync_profile_date_on_reversal(session, soldier=soldier, assignment=assignment, range_type=event.range_type, event_date=event.date)

    # Apply the new side effect.
    if status == RangeAttendanceStatus.present:
        valid_until = event.date + timedelta(days=_validity_days(session, event.range_type))
        _record_qualification(
            session, soldier_id=assignment.soldier_id, range_type=event.range_type,
            valid_until=valid_until, source_range_assignment_id=assignment.id,
        )
        _sync_profile_date_on_present(soldier, range_type=event.range_type, event_date=event.date)
        if present_correction:
            commander_id = _direct_commander_id(session, assignment.soldier_id)
            _range_notification(
                session, soldier_id=assignment.soldier_id, type=NotificationType.range_attendance_corrected_to_present,
                title="תיקון נוכחות במטווח", body=note, reference_type="range_assignment",
                reference_id=assignment.id, actor_id=marked_by,
            )
            if commander_id is not None:
                _range_notification(
                    session, soldier_id=commander_id, type=NotificationType.range_attendance_corrected_to_present,
                    title="תיקון נוכחות במטווח", body=note, reference_type="range_assignment",
                    reference_id=assignment.id, actor_id=marked_by,
                )
    elif status == RangeAttendanceStatus.no_show:
        adjustment = create_adjustment(
            session, soldier_id=assignment.soldier_id, delta=_NO_SHOW_PENALTY,
            reason="range_no_show", actor_id=marked_by,
        )
        assignment.score_adjustment_id = adjustment.id
        _range_notification(
            session, soldier_id=assignment.soldier_id, type=NotificationType.no_show_marked,
            title="נרשם היעדרות ממטווח", body=note, reference_type="range_assignment",
            reference_id=assignment.id, actor_id=marked_by,
        )
        if no_show_transition and _mitvachim_enabled(session):
            _range_notification(session, soldier_id=assignment.soldier_id, type=NotificationType.range_no_show, title="Range no-show recorded", body=f"{_range_context(session, event, reason=note)} | assignment={assignment.id}", reference_type="range_event", reference_id=event.id, actor_id=marked_by)
            notify_duty_managers_in_scope(
                session, soldier_id=assignment.soldier_id, type=NotificationType.range_no_show,
                title="Range no-show recorded",
                body=f"{_range_context(session, event, reason=note)} | assignment={assignment.id}",
                reference_type="range_event", reference_id=event.id, actor_id=marked_by,
            )
            commander_id = _direct_commander_id(session, assignment.soldier_id)
            if commander_id is not None:
                _range_notification(
                    session, soldier_id=commander_id, type=NotificationType.range_absence_reported_to_commander,
                    title="נרשמה היעדרות ממטווח", body=note, reference_type="range_assignment",
                    reference_id=assignment.id, actor_id=marked_by,
                )

    assignment.attendance_status = status
    assignment.marked_by = marked_by
    assignment.marked_at = datetime.now(UTC)
    assignment.note = note

    from app.db.models import DutyAssignment as _DutyAssignment
    from app.services.duty_eligibility_watch import recheck_assignments

    affected_ids = session.execute(
        select(_DutyAssignment.id).where(
            _DutyAssignment.soldier_id == assignment.soldier_id,
            _DutyAssignment.status == "published",
        )
    ).scalars().all()
    if affected_ids:
        recheck_assignments(session, affected_ids)

    write_audit(
        session, actor_id=marked_by, action="range_attendance_marked", entity_type="range_assignment",
        entity_id=assignment.id, before={"attendance_status": previous_status}, after={"attendance_status": status},
    )

    session.commit()
    session.refresh(assignment)
    return assignment
