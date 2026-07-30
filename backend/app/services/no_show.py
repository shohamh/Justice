from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyAssignment, DutyNoShow, NotificationType
from app.services.adjustments import create_adjustment
from app.services.notifications import create_notification

_DEFAULT_PENALTY = Decimal("-1")


class NoShowError(Exception):
    """Raised on an invalid no-show marking operation."""


def mark_no_show(
    session: Session,
    *,
    duty_assignment_id: uuid.UUID,
    marked_by: uuid.UUID,
    note: str,
    penalty_delta: Decimal = _DEFAULT_PENALTY,
) -> DutyNoShow:
    if not note or not note.strip():
        raise NoShowError("note_required")
    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        raise NoShowError("assignment_not_found")
    if assignment.end_date >= date.today():
        raise NoShowError("duty_not_yet_finished")
    existing = session.execute(
        select(DutyNoShow).where(DutyNoShow.duty_assignment_id == duty_assignment_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise NoShowError("already_marked")

    adj = create_adjustment(
        session,
        soldier_id=assignment.soldier_id,
        delta=penalty_delta,
        reason=f"אי-הופעה לתורנות {assignment.start_date.isoformat()}",
        duty_type_id=assignment.duty_type_id,
        actor_id=marked_by,
    )

    record = DutyNoShow(
        duty_assignment_id=duty_assignment_id,
        soldier_id=assignment.soldier_id,
        marked_by=marked_by,
        note=note,
        score_adjustment_id=adj.id,
    )
    session.add(record)
    session.flush()

    create_notification(
        session, soldier_id=assignment.soldier_id, type=NotificationType.no_show_marked,
        title="נרשמה אי-הופעה לתורנות שלך", reference_type="duty_no_show", reference_id=record.id,
        actor_id=marked_by,
    )
    write_audit(
        session, actor_id=marked_by, action="no_show.mark", entity_type="duty_no_show",
        entity_id=record.id,
        after={
            "duty_assignment_id": str(duty_assignment_id),
            "soldier_id": str(assignment.soldier_id),
            "note": note,
            "score_adjustment_id": str(adj.id),
        },
    )
    return record


def count_no_shows(session: Session, *, soldier_id: uuid.UUID, since: date | None = None) -> int:
    query = select(DutyNoShow).where(DutyNoShow.soldier_id == soldier_id)
    if since is not None:
        query = query.where(
            DutyNoShow.created_at >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
        )
    return len(list(session.execute(query).scalars().all()))


def list_no_shows(session: Session, *, soldier_id: uuid.UUID) -> list[DutyNoShow]:
    return list(
        session.execute(
            select(DutyNoShow)
            .where(DutyNoShow.soldier_id == soldier_id)
            .order_by(DutyNoShow.created_at.desc())
        )
        .scalars()
        .all()
    )
