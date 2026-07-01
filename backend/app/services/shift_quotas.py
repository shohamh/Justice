from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyShift, DutyShiftNodeQuota, HierarchyNode


class ShiftQuotaError(Exception):
    """Raised on invalid shift quota operations."""


def get_shift_quotas(session: Session, *, shift_id: uuid.UUID) -> list[DutyShiftNodeQuota]:
    return list(
        session.execute(
            select(DutyShiftNodeQuota).where(DutyShiftNodeQuota.duty_shift_id == shift_id)
        ).scalars().all()
    )


def set_shift_quotas(
    session: Session,
    *,
    shift_id: uuid.UUID,
    quotas: list[tuple[uuid.UUID, int]],
    actor_id: uuid.UUID | None = None,
) -> list[DutyShiftNodeQuota]:
    """Replace all quota entries for a shift. Validates node existence, no
    duplicate nodes, and that the sum does not exceed required_count."""
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        raise ShiftQuotaError("shift not found")

    seen: set[uuid.UUID] = set()
    total = 0
    for node_id, count in quotas:
        if node_id in seen:
            raise ShiftQuotaError(f"duplicate node {node_id} in quotas")
        seen.add(node_id)
        if count < 1:
            raise ShiftQuotaError(f"count must be >= 1 for node {node_id}")
        if session.get(HierarchyNode, node_id) is None:
            raise ShiftQuotaError(f"hierarchy node {node_id} not found")
        total += count

    if total > shift.required_count:
        raise ShiftQuotaError(
            f"sum of quota counts ({total}) exceeds required_count ({shift.required_count})"
        )

    existing = get_shift_quotas(session, shift_id=shift_id)
    before = [{"node_id": str(q.hierarchy_node_id), "count": q.count} for q in existing]

    session.execute(delete(DutyShiftNodeQuota).where(DutyShiftNodeQuota.duty_shift_id == shift_id))
    session.flush()

    entries = [
        DutyShiftNodeQuota(duty_shift_id=shift_id, hierarchy_node_id=node_id, count=count)
        for node_id, count in quotas
    ]
    for e in entries:
        session.add(e)
    session.flush()

    after = [{"node_id": str(node_id), "count": count} for node_id, count in quotas]
    write_audit(
        session,
        actor_id=actor_id,
        action="shift.set_node_quotas",
        entity_type="duty_shift",
        entity_id=shift_id,
        before=before,
        after=after,
    )
    return entries
