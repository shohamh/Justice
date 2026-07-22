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


def _used_days_in_period(
    session: Session, soldier_id: uuid.UUID, period_start: date, period_end: date
) -> int:
    """Days already claimed (pending/approved) by `soldier_id` that overlap
    [period_start, period_end) — the same overlap/clipping logic remaining_days()
    uses, factored out so both read (remaining_days) and enforcement
    (submit_constraint's cap check) always agree on what "used" means."""
    rows = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == soldier_id,
            PersonalConstraint.status.in_(["pending", "approved"]),
            PersonalConstraint.start_date < period_end,
            PersonalConstraint.end_date >= period_start,
        )
    ).scalars().all()
    used = 0
    for r in rows:
        overlap_start = max(r.start_date, period_start)
        overlap_end = min(r.end_date, date.fromordinal(period_end.toordinal() - 1))
        used += (overlap_end - overlap_start).days + 1
    return used


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

    cap_days = int(_get_setting_with_default(session, "constraints.personal_cap_days", 15))
    reset_period = str(_get_setting_with_default(session, "constraints.reset_period", "quarter"))

    # I-2: enforcement is period-scoped to match remaining_days()'s displayed
    # number — a soldier's already-claimed days in a period OTHER than the one
    # a given day of the new request falls into no longer count against it.
    # Design decision for requests straddling a period boundary: each touched
    # period is checked independently against its own remaining cap (existing
    # usage in that period + the new request's day-count clipped to that
    # period), rather than summing the whole request against a single period's
    # cap. This matches how remaining_days() already clips usage per period,
    # and rejects a request as soon as ANY touched period would be exceeded.
    cursor = start_date
    while cursor <= end_date:
        period_start, period_end = period_bounds(reset_period, cursor)
        existing_used = _used_days_in_period(session, soldier_id, period_start, period_end)
        overlap_start = max(start_date, period_start)
        overlap_end = min(end_date, date.fromordinal(period_end.toordinal() - 1))
        new_days_in_period = (overlap_end - overlap_start).days + 1
        if existing_used + new_days_in_period > cap_days:
            raise ConstraintError("cap_exceeded")
        cursor = period_end

    require_approval = bool(
        _get_setting_with_default(session, "constraints.require_manager_approval", True)
    )
    if require_approval:
        c = PersonalConstraint(
            soldier_id=soldier_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status="pending",
        )
    else:
        now = datetime.now(UTC)
        c = PersonalConstraint(
            soldier_id=soldier_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status="approved",
            decided_by=actor_id,
            decided_at=now,
        )

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
    if c.status == "pending":
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
    if c.status != "pending":
        raise ConstraintError("not_pending")
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
        session,
        actor_id=actor_id,
        action="constraint.approve",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": "pending"},
        after={"status": "approved", "decision_note": decision_note},
    )
    return c


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
    if c.status != "pending":
        raise ConstraintError("not_pending")
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
        before={"status": "pending"},
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
    if c.status != "pending":
        raise ConstraintError("not_pending")
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.cancel",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": "pending"},
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
                PersonalConstraint.status == "pending",
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
                    PersonalConstraint.status == "pending",
                    PersonalConstraint.soldier_id.in_(soldier_ids),
                )
            )
            .scalars()
            .all()
        )
    )


def period_bounds(reset_period: str, today: date) -> tuple[date, date]:
    """Inclusive start / exclusive end of the reset period containing `today`."""
    if reset_period == "half_year":
        start_month = 1 if today.month <= 6 else 7
        start = date(today.year, start_month, 1)
        end = date(today.year, 7, 1) if start_month == 1 else date(today.year + 1, 1, 1)
        return start, end
    if reset_period == "year":
        return date(today.year, 1, 1), date(today.year + 1, 1, 1)
    q_start_month = ((today.month - 1) // 3) * 3 + 1
    start = date(today.year, q_start_month, 1)
    end_month = q_start_month + 3
    end = date(today.year, end_month, 1) if end_month <= 12 else date(today.year + 1, 1, 1)
    return start, end


def remaining_days(session: Session, *, soldier_id: uuid.UUID, today: date | None = None) -> dict:
    today = today or date.today()
    reset_period = str(_get_setting_with_default(session, "constraints.reset_period", "quarter"))
    period_start, period_end = period_bounds(reset_period, today)
    cap_days = int(_get_setting_with_default(session, "constraints.personal_cap_days", 15))
    used = _used_days_in_period(session, soldier_id, period_start, period_end)
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
