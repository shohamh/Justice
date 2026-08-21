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


def _has_ever_been_deputy(session: Session, *, soldier_id: uuid.UUID, role: str) -> bool:
    """True iff `soldier_id` has ANY RoleDeputy row (as the deputy, past,
    present, or future) for `role` — used to block naming a current/former/
    future deputy as someone else's principal (no recursion).

    This is deliberately date-UNBOUNDED, not just overlap-with-the-new-
    grant's-window: `is_commander`/`is_duty_manager` (which decide whether
    the principal "holds the role" at all) are evaluated as of TODAY, so a
    window-overlap-only check here would create a gap — e.g. a soldier whose
    own deputy grant is active today (making is_commander(...) True today)
    could still be handed a brand new, non-overlapping FUTURE deputy grant
    as principal, producing a sub-deputy with no real permissions once their
    own grant ends. Blocking on any row at all closes that gap."""
    return session.execute(
        select(RoleDeputy.id).where(
            RoleDeputy.deputy_id == soldier_id,
            RoleDeputy.role == role,
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

    # No recursion: reject if the *principal* has EVER (past, present, or
    # future) been someone else's deputy for this role. See
    # _has_ever_been_deputy's docstring for why this must be date-unbounded
    # rather than limited to overlap with this grant's window.
    if _has_ever_been_deputy(session, soldier_id=principal_id, role=role):
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
