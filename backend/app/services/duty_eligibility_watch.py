# backend/app/services/duty_eligibility_watch.py
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyType, NotificationType, Soldier
from app.services.approval_scope import commander_chain_for_soldier
from app.services.notifications import create_notification, notify_duty_managers_in_scope
from app.services.weapon_eligibility import compute_eligibility

_WEAPON_INELIGIBLE_TITLE = "אינך כשיר לתורנות המשובצת"


def _reason_body(soldier_name: str, duty_type_name: str, start_date) -> str:
    return f"{soldier_name} אינו/ה כשיר/ה מבחינת הכשרת נשק לתורנות '{duty_type_name}' בתאריך {start_date.isoformat()}."


def recheck_assignments(session: Session, assignment_ids: Sequence[uuid.UUID]) -> int:
    """Re-evaluate weapon eligibility for the given assignment ids, updating the
    cache columns on each. Sends notifications only on a False->True transition
    (soldier just became ineligible). True->False is updated silently. Assignments
    that are not `published`, or whose duty type doesn't require a weapon tier,
    are skipped entirely. Returns the count of False->True transitions."""
    if not assignment_ids:
        return 0

    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.id.in_(assignment_ids),
            DutyAssignment.status == "published",
        )
    ).scalars().all()
    if not assignments:
        return 0

    type_ids = {a.duty_type_id for a in assignments}
    types_by_id = {
        dt.id: dt
        for dt in session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars()
    }

    newly_ineligible = 0
    for assignment in assignments:
        duty_type = types_by_id.get(assignment.duty_type_id)
        if duty_type is None or duty_type.required_range_type is None:
            continue

        eligible, reason = compute_eligibility(
            session, soldier_id=assignment.soldier_id,
            required_range_type=duty_type.required_range_type, as_of=assignment.start_date,
        )
        was_ineligible = assignment.weapon_ineligible
        now_ineligible = not eligible

        if now_ineligible == was_ineligible:
            continue

        assignment.weapon_ineligible = now_ineligible
        if now_ineligible:
            assignment.weapon_ineligible_reason = "אין הכשרת נשק בתוקף לתאריך התורנות"
            assignment.weapon_ineligible_detected_at = datetime.now(UTC)
            newly_ineligible += 1

            soldier = session.get(Soldier, assignment.soldier_id)
            soldier_name = soldier.full_name if soldier else ""
            body = _reason_body(soldier_name, duty_type.name, assignment.start_date)

            create_notification(
                session, soldier_id=assignment.soldier_id, type=NotificationType.weapon_ineligible_detected,
                title=_WEAPON_INELIGIBLE_TITLE, body=body,
                reference_type="duty_assignment", reference_id=assignment.id,
            )
            notify_duty_managers_in_scope(
                session, soldier_id=assignment.soldier_id, type=NotificationType.weapon_ineligible_detected,
                title=_WEAPON_INELIGIBLE_TITLE, body=body,
                reference_type="duty_assignment", reference_id=assignment.id,
            )
            chain = commander_chain_for_soldier(session, assignment.soldier_id)
            if chain:
                create_notification(
                    session, soldier_id=chain[0], type=NotificationType.weapon_ineligible_detected,
                    title=_WEAPON_INELIGIBLE_TITLE, body=body,
                    reference_type="duty_assignment", reference_id=assignment.id,
                )
        else:
            assignment.weapon_ineligible_reason = None
            assignment.weapon_ineligible_detected_at = None

    session.commit()
    return newly_ineligible
