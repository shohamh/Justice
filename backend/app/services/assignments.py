from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.algorithm.duration import combine_date_time
from app.algorithm.rest import last_duty_day, rest_violated
from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyLocation,
    DutyShift,
    DutyType,
    ExemptionDutyTypeMap,
    NotificationType,
    Soldier,
    SoldierExemption,
)
from app.services.notifications import create_notification
from app.services.rest import effective_assignment_end, resolve_rest_hours
from app.services.settings_loader import get_setting_int

_OVERRIDE_REASONS = {"replacement", "no_show_covered", "cancelled", "manual_edit"}


class AssignmentError(Exception):
    """Raised on an invalid assignment operation."""


def _has_overlap(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    q = select(DutyAssignment.id).where(
        DutyAssignment.soldier_id == soldier_id,
        DutyAssignment.status != "cancelled",
        DutyAssignment.start_date < end_date,
        DutyAssignment.end_date > start_date,
    )
    if exclude_id is not None:
        q = q.where(DutyAssignment.id != exclude_id)
    return session.execute(q).first() is not None


def _has_insufficient_rest(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    duty_type_id: uuid.UUID,
    start_date: date,
    end_date: date,
    start_time: str,
    end_time: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    q = select(DutyAssignment).where(
        DutyAssignment.soldier_id == soldier_id,
        DutyAssignment.status != "cancelled",
    )
    if exclude_id is not None:
        q = q.where(DutyAssignment.id != exclude_id)
    others = session.execute(q).scalars().all()
    if not others:
        return False

    default_rest_hours = get_setting_int(session, "duty.default_rest_hours", 12)
    this_type = session.get(DutyType, duty_type_id)
    this_rest_hours = resolve_rest_hours(this_type, default_rest_hours) if this_type else default_rest_hours
    this_last_day = last_duty_day(start_date, end_date)
    this_end_dt = combine_date_time(this_last_day, end_time)

    for other in others:
        if other.start_date >= end_date:
            # other starts after this one ends: this one's rest_hours must be
            # satisfied before other's start.
            if rest_violated(this_end_dt, other.start_date, other.start_time, this_rest_hours):
                return True
        elif other.end_date <= start_date:
            # other ends before this one starts: other's rest_hours must be
            # satisfied before this one's start.
            other_type = session.get(DutyType, other.duty_type_id)
            other_rest_hours = (
                resolve_rest_hours(other_type, default_rest_hours) if other_type else default_rest_hours
            )
            other_end_dt = effective_assignment_end(session, other)
            if rest_violated(other_end_dt, start_date, start_time, other_rest_hours):
                return True
    return False


def _has_blocking_exemption(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    duty_type_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> bool:
    covering = select(ExemptionDutyTypeMap.exemption_type_id).where(
        ExemptionDutyTypeMap.duty_type_id == duty_type_id
    )
    q = select(SoldierExemption.id).where(
        SoldierExemption.soldier_id == soldier_id,
        SoldierExemption.exemption_type_id.in_(covering),
        SoldierExemption.start_date < end_date,
        or_(SoldierExemption.end_date.is_(None), SoldierExemption.end_date >= start_date),
    )
    return session.execute(q).first() is not None


def create_assignment(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    start_date: date,
    end_date: date,
    notes: str | None = None,
    duty_shift_id: uuid.UUID | None = None,
    is_reserve: bool = False,
    actor_id: uuid.UUID | None = None,
) -> DutyAssignment:
    if end_date <= start_date:
        raise AssignmentError("bad_date_range")
    if session.get(Soldier, soldier_id) is None:
        raise AssignmentError("soldier_not_found")
    if session.get(DutyType, duty_type_id) is None:
        raise AssignmentError("duty_type_not_found")
    if session.get(DutyLocation, duty_location_id) is None:
        raise AssignmentError("location_not_found")
    start_time, end_time = "00:00", "23:59"
    if duty_shift_id is not None:
        shift = session.get(DutyShift, duty_shift_id)
        if shift is not None:
            start_time, end_time = shift.start_time, shift.end_time
    if _has_overlap(session, soldier_id=soldier_id, start_date=start_date, end_date=end_date):
        raise AssignmentError("overlap")
    if _has_insufficient_rest(
        session,
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
    ):
        raise AssignmentError("insufficient_rest")
    if _has_blocking_exemption(
        session,
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        start_date=start_date,
        end_date=end_date,
    ):
        raise AssignmentError("exempted")
    a = DutyAssignment(
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
        duty_shift_id=duty_shift_id,
        is_reserve=is_reserve,
        created_by=actor_id,
    )
    session.add(a)
    session.flush()
    create_notification(session, soldier_id=a.soldier_id,
                        type=NotificationType.assignment_created,
                        title="שיבוץ חדש נוצר עבורך",
                        reference_type="duty_assignment", reference_id=a.id,
                        actor_id=actor_id)
    write_audit(
        session,
        actor_id=actor_id,
        action="assignment.create",
        entity_type="duty_assignment",
        entity_id=a.id,
        after={
            "soldier_id": str(soldier_id),
            "duty_type_id": str(duty_type_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    return a


def cancel_assignment(
    session: Session, *, assignment: DutyAssignment, reason: str, actor_id: uuid.UUID | None = None
) -> DutyAssignment:
    if not reason or not reason.strip():
        raise AssignmentError("reason_required")
    before = {"status": assignment.status}
    assignment.status = "cancelled"
    create_notification(session, soldier_id=assignment.soldier_id,
                        type=NotificationType.assignment_removed,
                        title="שיבוץ בוטל",
                        reference_type="duty_assignment", reference_id=assignment.id,
                        actor_id=actor_id)
    write_audit(
        session,
        actor_id=actor_id,
        action="assignment.cancel",
        entity_type="duty_assignment",
        entity_id=assignment.id,
        before=before,
        after={"status": "cancelled"},
        context={"reason": reason},
    )
    return assignment


def _day_busy(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    on_date: date,
    exclude_assignment_id: uuid.UUID | None = None,
) -> bool:
    q = select(DutyAssignment.id).where(
        DutyAssignment.soldier_id == soldier_id,
        DutyAssignment.status != "cancelled",
        DutyAssignment.start_date <= on_date,
        DutyAssignment.end_date > on_date,
    )
    if exclude_assignment_id is not None:
        q = q.where(DutyAssignment.id != exclude_assignment_id)
    return session.execute(q).first() is not None


def _notify_day_override_change(
    session: Session,
    *,
    assignment: DutyAssignment,
    date: date,
    old_effective_id: uuid.UUID | None,
    new_effective_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
) -> None:
    if old_effective_id == new_effective_id:
        return
    date_str = date.isoformat()
    if old_effective_id is not None:
        create_notification(
            session, soldier_id=old_effective_id,
            type=NotificationType.assignment_removed,
            title=f"בוטל שיבוץ יומי עבורך בתאריך {date_str}",
            reference_type="duty_assignment", reference_id=assignment.id,
            actor_id=actor_id,
        )
    if new_effective_id is not None:
        create_notification(
            session, soldier_id=new_effective_id,
            type=NotificationType.assignment_created,
            title=f"שובצת ליום {date_str} כתחליף",
            reference_type="duty_assignment", reference_id=assignment.id,
            actor_id=actor_id,
        )


def set_day_override(
    session: Session,
    *,
    assignment: DutyAssignment,
    date: date,
    effective_soldier_id: uuid.UUID | None,
    reason: str,
    actor_id: uuid.UUID | None = None,
) -> DutyDayOverride:
    if not (assignment.start_date <= date < assignment.end_date):
        raise AssignmentError("date_out_of_range")
    if reason not in _OVERRIDE_REASONS:
        raise AssignmentError("bad_reason")
    if effective_soldier_id is not None:
        if session.get(Soldier, effective_soldier_id) is None:
            raise AssignmentError("soldier_not_found")
        if _day_busy(
            session,
            soldier_id=effective_soldier_id,
            on_date=date,
            exclude_assignment_id=assignment.id,
        ):
            raise AssignmentError("overlap")
        if _has_blocking_exemption(
            session,
            soldier_id=effective_soldier_id,
            duty_type_id=assignment.duty_type_id,
            start_date=date,
            end_date=date,
        ):
            raise AssignmentError("exempted")
    existing = session.execute(
        select(DutyDayOverride).where(
            DutyDayOverride.duty_assignment_id == assignment.id, DutyDayOverride.date == date
        )
    ).scalar_one_or_none()
    after = {
        "effective_soldier_id": str(effective_soldier_id) if effective_soldier_id else None,
        "reason": reason,
    }
    if existing is not None:
        old_effective_id = existing.effective_soldier_id
        before = {
            "effective_soldier_id": str(old_effective_id) if old_effective_id else None,
            "reason": existing.reason,
        }
        existing.effective_soldier_id = effective_soldier_id
        existing.reason = reason
        write_audit(
            session,
            actor_id=actor_id,
            action="assignment.override",
            entity_type="duty_day_override",
            entity_id=existing.id,
            before=before,
            after=after,
        )
        _notify_day_override_change(
            session, assignment=assignment, date=date,
            old_effective_id=old_effective_id, new_effective_id=effective_soldier_id,
            actor_id=actor_id,
        )
        return existing
    ov = DutyDayOverride(
        duty_assignment_id=assignment.id,
        date=date,
        effective_soldier_id=effective_soldier_id,
        reason=reason,
        created_by=actor_id,
    )
    session.add(ov)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="assignment.override",
        entity_type="duty_day_override",
        entity_id=ov.id,
        after=after,
    )
    _notify_day_override_change(
        session, assignment=assignment, date=date,
        old_effective_id=None, new_effective_id=effective_soldier_id,
        actor_id=actor_id,
    )
    return ov


def clear_day_override(
    session: Session, *, assignment: DutyAssignment, date: date, actor_id: uuid.UUID | None = None
) -> None:
    ov = session.execute(
        select(DutyDayOverride).where(
            DutyDayOverride.duty_assignment_id == assignment.id, DutyDayOverride.date == date
        )
    ).scalar_one_or_none()
    if ov is None:
        return  # idempotent
    write_audit(
        session,
        actor_id=actor_id,
        action="assignment.override_clear",
        entity_type="duty_day_override",
        entity_id=ov.id,
        before={
            "effective_soldier_id": str(ov.effective_soldier_id)
            if ov.effective_soldier_id
            else None
        },
    )
    _notify_day_override_change(
        session, assignment=assignment, date=date,
        old_effective_id=ov.effective_soldier_id, new_effective_id=None,
        actor_id=actor_id,
    )
    session.delete(ov)


def list_assignments(
    session: Session,
    *,
    soldier_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DutyAssignment]:
    q = select(DutyAssignment).where(DutyAssignment.status != "cancelled")
    if soldier_id is not None:
        q = q.where(DutyAssignment.soldier_id == soldier_id)
    if date_from is not None:
        q = q.where(DutyAssignment.end_date > date_from)
    if date_to is not None:
        q = q.where(DutyAssignment.start_date <= date_to)
    return list(session.execute(q.order_by(DutyAssignment.start_date)).scalars().all())


def list_assignments_for_soldiers(
    session: Session,
    *,
    soldier_ids: list[uuid.UUID],
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[DutyAssignment]:
    if not soldier_ids:
        return []
    q = select(DutyAssignment).where(
        DutyAssignment.status != "cancelled", DutyAssignment.soldier_id.in_(soldier_ids)
    )
    if date_from is not None:
        q = q.where(DutyAssignment.end_date > date_from)
    if date_to is not None:
        q = q.where(DutyAssignment.start_date <= date_to)
    return list(session.execute(q.order_by(DutyAssignment.start_date)).scalars().all())
