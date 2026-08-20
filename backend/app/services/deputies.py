from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.authz import is_commander, is_duty_manager
from app.db.models import RoleDeputy, Soldier


class DeputyError(Exception):
    pass


def _is_active_deputy(
    session: Session, *, soldier_id: uuid.UUID, role: str, window_start: date, window_end: date
) -> bool:
    """True iff `soldier_id` already has a RoleDeputy row (as the deputy) for
    `role` overlapping [window_start, window_end] — used to block naming a
    current deputy as someone else's principal (no recursion)."""
    return session.execute(
        select(RoleDeputy.id).where(
            RoleDeputy.deputy_id == soldier_id,
            RoleDeputy.role == role,
            RoleDeputy.start_date <= window_end,
            RoleDeputy.end_date >= window_start,
        ).limit(1)
    ).first() is not None


def create_deputy(
    session: Session,
    *,
    principal_id: uuid.UUID,
    deputy_id: uuid.UUID,
    role: str,
    start_date: date,
    end_date: date,
    actor_id: uuid.UUID | None,
) -> RoleDeputy:
    if role not in ("commander", "duty_manager"):
        raise DeputyError("invalid_role")
    if end_date < start_date:
        raise DeputyError("invalid_date_range")
    if principal_id == deputy_id:
        raise DeputyError("cannot_deputize_self")
    if session.get(Soldier, principal_id) is None:
        raise DeputyError("principal_not_found")
    if session.get(Soldier, deputy_id) is None:
        raise DeputyError("deputy_not_found")

    holds_role = is_commander(session, principal_id) if role == "commander" else is_duty_manager(session, principal_id)
    if not holds_role:
        raise DeputyError("principal_lacks_role")

    # No recursion: reject if the *principal* is themselves currently (for
    # any part of this window) someone else's active deputy for this role.
    if _is_active_deputy(session, soldier_id=principal_id, role=role, window_start=start_date, window_end=end_date):
        raise DeputyError("cannot_deputize_a_deputy")

    existing = session.execute(
        select(RoleDeputy).where(
            RoleDeputy.principal_id == principal_id,
            RoleDeputy.deputy_id == deputy_id,
            RoleDeputy.role == role,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DeputyError("already_exists")

    entry = RoleDeputy(
        principal_id=principal_id, deputy_id=deputy_id, role=role,
        start_date=start_date, end_date=end_date, created_by=actor_id,
    )
    session.add(entry)
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="deputy.create", entity_type="role_deputy",
        entity_id=entry.id,
        after={
            "principal_id": str(principal_id), "deputy_id": str(deputy_id), "role": role,
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        },
    )
    return entry


def list_deputies(session: Session, *, principal_id: uuid.UUID) -> list[RoleDeputy]:
    return list(
        session.execute(
            select(RoleDeputy)
            .where(RoleDeputy.principal_id == principal_id)
            .order_by(RoleDeputy.start_date.desc())
        ).scalars().all()
    )


def list_active_deputies_for(
    session: Session, *, deputy_id: uuid.UUID, today: date | None = None
) -> list[RoleDeputy]:
    """Grants where `deputy_id` is currently acting as someone's deputy."""
    today = today or date.today()
    return list(
        session.execute(
            select(RoleDeputy).where(
                RoleDeputy.deputy_id == deputy_id,
                RoleDeputy.start_date <= today,
                RoleDeputy.end_date >= today,
            )
        ).scalars().all()
    )


def revoke_deputy(session: Session, *, deputy_grant_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    entry = session.get(RoleDeputy, deputy_grant_id)
    if entry is None:
        raise DeputyError("deputy_grant_not_found")
    before = {
        "principal_id": str(entry.principal_id), "deputy_id": str(entry.deputy_id), "role": entry.role,
    }
    session.delete(entry)
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="deputy.revoke", entity_type="role_deputy",
        entity_id=deputy_grant_id, before=before,
    )
