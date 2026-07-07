from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import ExemptionType, Soldier, SoldierExemption


class ExemptionError(Exception):
    """Raised on an invalid exemption operation."""


def grant_exemption(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None,
    reason: str | None,
    actor_id: uuid.UUID | None = None,
) -> SoldierExemption:
    if session.get(Soldier, soldier_id) is None:
        raise ExemptionError("soldier_not_found")
    if session.get(ExemptionType, exemption_type_id) is None:
        raise ExemptionError("exemption_type_not_found")
    if end_date is not None and end_date < start_date:
        raise ExemptionError("bad_date_range")
    ex = SoldierExemption(
        soldier_id=soldier_id,
        exemption_type_id=exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        granted_by=actor_id,
    )
    session.add(ex)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption.grant",
        entity_type="soldier_exemption",
        entity_id=ex.id,
        after={
            "soldier_id": str(soldier_id),
            "exemption_type_id": str(exemption_type_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat() if end_date else None,
        },
    )
    return ex


def grant_commander_exemption(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None = None,
    reason: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> SoldierExemption:
    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise ExemptionError("exemption_type_not_found")
    if not et.is_commander_exemption:
        raise ExemptionError("not_commander_exemption_type")
    if session.get(Soldier, soldier_id) is None:
        raise ExemptionError("soldier_not_found")
    if end_date is not None and end_date < start_date:
        raise ExemptionError("bad_date_range")
    ex = SoldierExemption(
        soldier_id=soldier_id,
        exemption_type_id=exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        granted_by=actor_id,
    )
    session.add(ex)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption.grant_commander",
        entity_type="soldier_exemption",
        entity_id=ex.id,
        after={"soldier_id": str(soldier_id), "exemption_type_id": str(exemption_type_id)},
        context={"reason": reason},
    )
    return ex


def revoke_exemption(
    session: Session,
    *,
    exemption_id: uuid.UUID,
    reason: str,
    actor_id: uuid.UUID,
) -> None:
    from app.db.models import NotificationType
    from app.services.notifications import create_notification, notify_duty_managers_in_scope

    ex = session.get(SoldierExemption, exemption_id)
    if ex is None:
        raise ExemptionError("exemption_not_found")
    today = date.today()
    if ex.end_date is not None and ex.end_date < today:
        # Already expired: revoking would otherwise push end_date forward to
        # today, re-opening a closed exemption. Treat as a true no-op — no
        # fields change, no notification.
        return

    before = {"end_date": ex.end_date.isoformat() if ex.end_date else None}
    if ex.start_date <= today:
        ex.end_date = today
    # Not-yet-started exemptions keep their original start_date/end_date —
    # historical accuracy — and rely entirely on revoked_at for "not in effect".
    ex.revoked_at = datetime.now(timezone.utc)
    ex.revoked_by = actor_id
    ex.revoke_reason = reason
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption.revoke",
        entity_type="soldier_exemption",
        entity_id=ex.id,
        before=before,
        after={"end_date": ex.end_date.isoformat() if ex.end_date else None, "revoked": True},
        context={"reason": reason},
    )
    session.flush()

    create_notification(
        session, soldier_id=ex.soldier_id,
        type=NotificationType.exemption_revoked,
        title="פטור בוטל",
        body=reason,
        reference_type="soldier_exemption", reference_id=ex.id,
        actor_id=actor_id,
    )
    notify_duty_managers_in_scope(
        session, soldier_id=ex.soldier_id,
        type=NotificationType.exemption_revoked,
        title="פטור בוטל",
        body=reason,
        reference_type="soldier_exemption", reference_id=ex.id,
        actor_id=actor_id,
    )


def list_exemptions(session: Session, *, soldier_id: uuid.UUID) -> list[SoldierExemption]:
    return list(
        session.execute(
            select(SoldierExemption)
            .where(SoldierExemption.soldier_id == soldier_id)
            .order_by(SoldierExemption.start_date)
        )
        .scalars()
        .all()
    )


def active_exemptions(
    session: Session, *, soldier_id: uuid.UUID, on_date: date
) -> list[SoldierExemption]:
    return list(
        session.execute(
            select(SoldierExemption).where(
                SoldierExemption.soldier_id == soldier_id,
                SoldierExemption.start_date <= on_date,
                or_(SoldierExemption.end_date.is_(None), SoldierExemption.end_date >= on_date),
            )
        )
        .scalars()
        .all()
    )
