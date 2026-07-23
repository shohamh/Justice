from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyManagerScope, HierarchyNode, Soldier


class DmScopeError(Exception):
    pass


def recompute_role(session: Session, soldier: Soldier) -> None:
    """Recompute the soldier's display-label role from real capability data.
    Priority: admin > commander > duty_manager > soldier. Never touches admins.
    This is a display label only — authorization no longer reads `role` for
    the commander/duty_manager distinction (see app/auth/authz.py)."""
    if soldier.role == "admin":
        return
    from app.auth.authz import is_commander, is_duty_manager

    if is_commander(session, soldier.id):
        soldier.role = "commander"
    elif is_duty_manager(session, soldier.id):
        soldier.role = "duty_manager"
    else:
        soldier.role = "soldier"


def assign_dm_scope(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    node_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> DutyManagerScope:
    if session.get(Soldier, soldier_id) is None:
        raise DmScopeError("soldier_not_found")
    if session.get(HierarchyNode, node_id) is None:
        raise DmScopeError("node_not_found")

    existing = session.execute(
        select(DutyManagerScope).where(
            DutyManagerScope.duty_manager_id == soldier_id,
            DutyManagerScope.hierarchy_node_id == node_id,
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    entry = DutyManagerScope(duty_manager_id=soldier_id, hierarchy_node_id=node_id)
    session.add(entry)

    soldier = session.get(Soldier, soldier_id)
    assert soldier is not None
    session.flush()
    recompute_role(session, soldier)
    write_audit(
        session,
        actor_id=actor_id,
        action="dm_scope.assign",
        entity_type="duty_manager_scope",
        entity_id=entry.id,
        after={"soldier_id": str(soldier_id), "node_id": str(node_id)},
    )
    return entry


def remove_dm_scope(
    session: Session,
    *,
    entry_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> None:
    entry = session.get(DutyManagerScope, entry_id)
    if entry is None:
        raise DmScopeError("scope_entry_not_found")

    soldier_id = entry.duty_manager_id
    session.delete(entry)
    session.flush()

    soldier = session.get(Soldier, soldier_id)
    if soldier is not None:
        recompute_role(session, soldier)

    write_audit(
        session,
        actor_id=actor_id,
        action="dm_scope.remove",
        entity_type="duty_manager_scope",
        entity_id=entry_id,
    )
