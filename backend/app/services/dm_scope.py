from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyManagerScope, HierarchyNode, Soldier


class DmScopeError(Exception):
    pass


def assign_dm_scope(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    node_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> DutyManagerScope:
    if session.get(Soldier, soldier_id) is None:
        raise DmScopeError("soldier not found")
    if session.get(HierarchyNode, node_id) is None:
        raise DmScopeError("node not found")

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
    if soldier.role not in ("duty_manager", "admin"):
        soldier.role = "duty_manager"

    session.flush()
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
        raise DmScopeError("scope entry not found")

    soldier_id = entry.duty_manager_id
    session.delete(entry)
    session.flush()

    remaining = session.execute(
        select(func.count()).where(DutyManagerScope.duty_manager_id == soldier_id)
    ).scalar_one()

    if remaining == 0:
        soldier = session.get(Soldier, soldier_id)
        if soldier is not None and soldier.role == "duty_manager":
            commanded = session.execute(
                select(func.count()).where(HierarchyNode.commander_id == soldier_id)
            ).scalar_one()
            soldier.role = "commander" if commanded > 0 else "soldier"

    write_audit(
        session,
        actor_id=actor_id,
        action="dm_scope.remove",
        entity_type="duty_manager_scope",
        entity_id=entry_id,
    )
