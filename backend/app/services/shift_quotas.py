from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyShift, DutyShiftNodeQuota, HierarchyNode
from app.services.potential import compute_potential


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


def compute_potential_split(
    session: Session, *, parent_node_id: uuid.UUID, required_count: int, reference_date: date | None = None
) -> list[dict]:
    """Proportionally split `required_count` across `parent_node_id`'s direct
    children, weighted by each child's final_potential (eligible-soldier count
    adjusted for exemptions/modifiers). Uses the largest-remainder method so
    counts always sum to exactly `required_count`. Falls back to an even split
    if every child has zero weight (otherwise the split would be all-zero and
    useless)."""
    if required_count < 1:
        raise ShiftQuotaError("required_count must be >= 1")

    children = list(
        session.execute(
            select(HierarchyNode)
            .where(HierarchyNode.parent_id == parent_node_id)
            .order_by(HierarchyNode.name)
        ).scalars().all()
    )
    if not children:
        raise ShiftQuotaError("parent node has no direct children")

    ref = reference_date or date.today()
    weights = [
        max(compute_potential(session, node_id=child.id, reference_date=ref).final_potential, 0)
        for child in children
    ]

    n = len(children)
    total_weight = sum(weights)
    if total_weight == 0:
        base, extra = divmod(required_count, n)
        shares = [base + (1 if i < extra else 0) for i in range(n)]
    else:
        raw_shares = [required_count * w / total_weight for w in weights]
        shares = [int(r) for r in raw_shares]
        remainder = required_count - sum(shares)
        order_by_fraction = sorted(
            range(n), key=lambda i: raw_shares[i] - shares[i], reverse=True
        )
        for i in order_by_fraction[:remainder]:
            shares[i] += 1

    return [
        {
            "hierarchy_node_id": child.id,
            "node_name": child.name,
            "count": shares[i],
            "weight": weights[i],
        }
        for i, child in enumerate(children)
    ]
