from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyNode, NotificationType, PersonalConstraint, Soldier, SoldierEnrollmentRequest
from app.services.date_validation import check_max_span
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting


class ConstraintError(Exception):
    """Raised on an invalid constraint operation."""


def _get_setting_with_default(session: Session, key: str, default):
    try:
        return get_setting(session, key)
    except SettingNotFound:
        return default


def submit_constraint(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
    reason: str,
    actor_id: uuid.UUID | None = None,
) -> PersonalConstraint:
    if session.get(Soldier, soldier_id) is None:
        raise ConstraintError("soldier_not_found")
    if end_date < start_date:
        raise ConstraintError("bad_date_range")
    check_max_span(start_date, end_date, ConstraintError)
    if start_date < date.today():
        raise ConstraintError("start_date_in_past")

    rd = remaining_days(session, soldier_id=soldier_id, today=start_date)
    cap_days = rd["cap_days"]
    used = rd["used_days"]
    period_start, period_end = rd["period_start"], rd["period_end"]
    period_last_day = date.fromordinal(period_end.toordinal() - 1)
    overlap_start = max(start_date, period_start)
    overlap_end = min(end_date, period_last_day)
    requested_in_period = max(0, (overlap_end - overlap_start).days + 1)
    if used + requested_in_period > cap_days:
        raise ConstraintError("cap_exceeded")

    require_commander = bool(
        _get_setting_with_default(session, "constraints.require_commander_approval", True)
    )
    require_dm = bool(
        _get_setting_with_default(session, "constraints.require_duty_manager_approval", True)
    )

    if require_commander:
        initial_status = "pending_commander"
    elif require_dm:
        initial_status = "pending_duty_manager"
    else:
        initial_status = "approved"

    c = PersonalConstraint(
        soldier_id=soldier_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status=initial_status,
    )
    if initial_status == "approved":
        c.decided_by = None
        c.decided_at = datetime.now(UTC)
        c.decision_note = "אושר אוטומטית - אין דרישת אישור מוגדרת"

    session.add(c)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.submit",
        entity_type="personal_constraint",
        entity_id=c.id,
        after={
            "soldier_id": str(soldier_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "reason": reason,
            "status": c.status,
        },
    )
    if c.status == "pending_commander":
        from app.services.notifications import notify_commanders_of_request
        notify_commanders_of_request(
            session,
            soldier_id=soldier_id,
            type=NotificationType.constraint_pending,
            title=f"בקשת אילוץ חדשה: {start_date} – {end_date}",
            body=reason,
            reference_type="personal_constraint",
            reference_id=c.id,
            actor_id=actor_id,
        )
    elif c.status == "pending_duty_manager":
        from app.services.notifications import notify_duty_managers_of_request
        notify_duty_managers_of_request(
            session,
            soldier_id=soldier_id,
            type=NotificationType.constraint_pending,
            title=f"בקשת אילוץ ממתינה לאישור: {start_date} – {end_date}",
            body=reason,
            reference_type="personal_constraint",
            reference_id=c.id,
            actor_id=actor_id,
        )
    return c


def _approve_commander_step(
    session: Session, c: PersonalConstraint, *, actor_id: uuid.UUID | None,
) -> PersonalConstraint:
    c.commander_approved_by = actor_id
    require_dm = bool(
        _get_setting_with_default(session, "constraints.require_duty_manager_approval", True)
    )
    if require_dm:
        c.status = "pending_duty_manager"
        session.flush()
        from app.services.notifications import notify_duty_managers_of_request
        notify_duty_managers_of_request(
            session,
            soldier_id=c.soldier_id,
            type=NotificationType.constraint_pending,
            title="בקשת אילוץ ממתינה לאישור (אושרה ע\"י מפקד)",
            body=c.reason,
            reference_type="personal_constraint",
            reference_id=c.id,
            actor_id=actor_id,
        )
    else:
        c.status = "approved"
        c.decided_by = actor_id
        c.decided_at = datetime.now(UTC)
        session.flush()
        create_notification(session, soldier_id=c.soldier_id,
                            type=NotificationType.constraint_approved,
                            title="בקשת האילוץ אושרה",
                            reference_type="personal_constraint", reference_id=c.id,
                            actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="constraint.approve_commander_step",
        entity_type="personal_constraint", entity_id=c.id,
        before={"status": "pending_commander"}, after={"status": c.status},
    )
    return c


def _approve_duty_manager_step(
    session: Session, c: PersonalConstraint, *, actor_id: uuid.UUID | None, decision_note: str | None,
) -> PersonalConstraint:
    c.status = "approved"
    c.decided_by = actor_id
    c.decided_at = datetime.now(UTC)
    c.decision_note = decision_note
    session.flush()
    create_notification(session, soldier_id=c.soldier_id,
                        type=NotificationType.constraint_approved,
                        title="בקשת האילוץ אושרה",
                        reference_type="personal_constraint", reference_id=c.id,
                        actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="constraint.approve_duty_manager_step",
        entity_type="personal_constraint", entity_id=c.id,
        before={"status": "pending_duty_manager"}, after={"status": "approved", "decision_note": decision_note},
    )
    return c


def approve_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    decision_note: str | None = None,
) -> PersonalConstraint:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    if c.status not in ("pending_commander", "pending_duty_manager"):
        raise ConstraintError("not_pending")
    unresolved_enrollment = session.execute(
        select(SoldierEnrollmentRequest).where(
            SoldierEnrollmentRequest.soldier_id == c.soldier_id,
            SoldierEnrollmentRequest.status.in_(("pending", "commander_approved")),
        )
    ).scalars().first()
    if unresolved_enrollment is not None:
        raise ConstraintError("enrollment_not_approved")

    if c.status == "pending_commander":
        return _approve_commander_step(session, c, actor_id=actor_id)
    return _approve_duty_manager_step(session, c, actor_id=actor_id, decision_note=decision_note)


def reject_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    decision_note: str,
) -> PersonalConstraint:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    if c.status not in ("pending_commander", "pending_duty_manager"):
        raise ConstraintError("not_pending")
    before_status = c.status
    c.status = "rejected"
    c.decided_by = actor_id
    c.decided_at = datetime.now(UTC)
    c.decision_note = decision_note
    session.flush()
    create_notification(session, soldier_id=c.soldier_id,
                        type=NotificationType.constraint_rejected,
                        title="בקשת האילוץ נדחתה",
                        reference_type="personal_constraint", reference_id=c.id,
                        actor_id=actor_id)
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.reject",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": before_status},
        after={"status": "rejected", "decision_note": decision_note},
    )
    return c


def cancel_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    # Only the first step (pending_commander) is cancelable. Reaching
    # pending_duty_manager always means the request has moved past the first
    # approval gate - either the commander step ran (via _approve_commander_step,
    # regardless of whether actor_id was supplied - an internal/system caller
    # passing actor_id=None must not make an already-approved request look
    # uncancelable to detect), or the commander step was configured off entirely
    # and the request started directly at pending_duty_manager. Either way the
    # request is already in front of the duty manager and should no longer be
    # withdrawable unilaterally. commander_approved_by is purely an attribution
    # field (who approved it, if anyone) - it must not gate cancel eligibility,
    # both because actor_id is optional and because the FK is ON DELETE SET NULL
    # (a later soldier deletion would silently flip it back to None).
    cancelable = c.status == "pending_commander"
    if not cancelable:
        raise ConstraintError("not_pending")
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.cancel",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": c.status},
        after={"deleted": True},
    )
    session.delete(c)


def list_constraints(session: Session, *, soldier_id: uuid.UUID) -> list[PersonalConstraint]:
    return list(
        session.execute(
            select(PersonalConstraint)
            .where(PersonalConstraint.soldier_id == soldier_id)
            .order_by(PersonalConstraint.created_at.desc())
        )
        .scalars()
        .all()
    )


def _scope_soldier_ids(session: Session, node_ids: set[uuid.UUID]) -> list[uuid.UUID]:
    """Return IDs of soldiers in scope: enrolled in scope nodes OR pending enrollment to them."""
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(node_ids)))
        .subquery()
    )
    enrolled = set(
        session.execute(
            select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
        ).scalars().all()
    )
    pending = set(
        session.execute(
            select(SoldierEnrollmentRequest.soldier_id).where(
                SoldierEnrollmentRequest.status == "pending",
                SoldierEnrollmentRequest.requested_node_id.in_(select(subq.c.id)),
            )
        ).scalars().all()
    )
    return list(enrolled | pending)


def list_pending_approvals(
    session: Session,
    *,
    node_ids: set[uuid.UUID],
) -> list[PersonalConstraint]:
    soldier_ids = _scope_soldier_ids(session, node_ids)
    return list(
        session.execute(
            select(PersonalConstraint)
            .where(
                PersonalConstraint.status.in_(("pending_commander", "pending_duty_manager")),
                PersonalConstraint.soldier_id.in_(soldier_ids),
            )
            .order_by(PersonalConstraint.start_date.asc())
        )
        .scalars()
        .all()
    )


def pending_approval_count(session: Session, *, node_ids: set[uuid.UUID]) -> int:
    soldier_ids = _scope_soldier_ids(session, node_ids)
    return len(
        list(
            session.execute(
                select(PersonalConstraint)
                .where(
                    PersonalConstraint.status.in_(("pending_commander", "pending_duty_manager")),
                    PersonalConstraint.soldier_id.in_(soldier_ids),
                )
            )
            .scalars()
            .all()
        )
    )


def period_bounds(reset_period: str, today: date) -> tuple[date, date]:
    """Inclusive start / exclusive end of the reset period containing `today`.

    `reset_period` is one of "quarter" (default), "half_year", "year" — plain
    calendar boundaries relative to `today`, no configurable anchor.
    """
    if reset_period == "half_year":
        start_month = 1 if today.month <= 6 else 7
        start = date(today.year, start_month, 1)
        end = date(today.year, 7, 1) if start_month == 1 else date(today.year + 1, 1, 1)
        return start, end
    if reset_period == "year":
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    # default: quarter
    q_start_month = ((today.month - 1) // 3) * 3 + 1
    start = date(today.year, q_start_month, 1)
    end_month = q_start_month + 3
    end = date(today.year, end_month, 1) if end_month <= 12 else date(today.year + 1, 1, 1)
    return start, end


def remaining_days(session: Session, *, soldier_id: uuid.UUID, today: date | None = None) -> dict:
    """Cap / used / remaining personal-constraint days for the reset period containing `today`.

    Counts pending + approved constraints overlapping the current period,
    clipped to the period's boundaries. `submit_constraint` uses this same
    logic (via this function) for its cap-exceeded check, so the "remaining"
    number shown in the UI stays consistent with what gets enforced.
    """
    today = today or date.today()
    reset_period = str(_get_setting_with_default(session, "constraints.reset_period", "quarter"))
    period_start, period_end = period_bounds(reset_period, today)
    cap_days = int(_get_setting_with_default(session, "constraints.personal_cap_days", 15))
    rows = list(
        session.execute(
            select(PersonalConstraint).where(
                PersonalConstraint.soldier_id == soldier_id,
                PersonalConstraint.status.in_(["pending_commander", "pending_duty_manager", "approved"]),
                PersonalConstraint.start_date < period_end,
                PersonalConstraint.end_date >= period_start,
            )
        )
        .scalars()
        .all()
    )
    used = 0
    period_last_day = date.fromordinal(period_end.toordinal() - 1)
    for r in rows:
        overlap_start = max(r.start_date, period_start)
        overlap_end = min(r.end_date, period_last_day)
        used += (overlap_end - overlap_start).days + 1
    return {
        "cap_days": cap_days,
        "used_days": used,
        "remaining_days": max(0, cap_days - used),
        "period_start": period_start,
        "period_end": period_end,
    }


def get_approved_constraint_dates(
    session: Session, *, soldier_id: uuid.UUID
) -> list[tuple[date, date]]:
    today = date.today()
    rows = list(
        session.execute(
            select(PersonalConstraint).where(
                PersonalConstraint.soldier_id == soldier_id,
                PersonalConstraint.status == "approved",
                PersonalConstraint.end_date >= today,
            )
        )
        .scalars()
        .all()
    )
    return [(r.start_date, r.end_date) for r in rows]
