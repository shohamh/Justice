from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyNode, NotificationType, PersonalConstraint, Soldier
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting


class ConstraintError(Exception):
    """Raised on an invalid constraint operation."""


def _get_setting_with_default(session: Session, key: str, default):
    try:
        return get_setting(session, key)
    except SettingNotFound:
        return default


def _future_cap_used(session: Session, soldier_id: uuid.UUID) -> int:
    today = date.today()
    rows = list(
        session.execute(
            select(PersonalConstraint).where(
                PersonalConstraint.soldier_id == soldier_id,
                PersonalConstraint.end_date >= today,
                PersonalConstraint.status.in_(["pending", "approved"]),
            )
        )
        .scalars()
        .all()
    )
    return sum((r.end_date - r.start_date).days + 1 for r in rows)


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
    if start_date < date.today():
        raise ConstraintError("start_date_in_past")

    cap_days = int(_get_setting_with_default(session, "constraints.personal_cap_days", 15))
    used = _future_cap_used(session, soldier_id)
    requested = (end_date - start_date).days + 1
    if used + requested > cap_days:
        raise ConstraintError("cap_exceeded")

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


def list_pending_approvals(
    session: Session,
    *,
    node_ids: set[uuid.UUID],
) -> list[PersonalConstraint]:
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(node_ids)))
        .subquery()
    )
    return list(
        session.execute(
            select(PersonalConstraint)
            .where(
                PersonalConstraint.status == "pending",
                PersonalConstraint.soldier_id.in_(
                    select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
                ),
            )
            .order_by(PersonalConstraint.start_date.asc())
        )
        .scalars()
        .all()
    )


def pending_approval_count(session: Session, *, node_ids: set[uuid.UUID]) -> int:
    subq = (
        select(HierarchyNode.id)
        .where(HierarchyNode.path_ids.overlap(list(node_ids)))
        .subquery()
    )
    return len(
        list(
            session.execute(
                select(PersonalConstraint)
                .where(
                    PersonalConstraint.status == "pending",
                    PersonalConstraint.soldier_id.in_(
                        select(Soldier.id).where(Soldier.hierarchy_node_id.in_(select(subq.c.id)))
                    ),
                )
            )
            .scalars()
            .all()
        )
    )


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
