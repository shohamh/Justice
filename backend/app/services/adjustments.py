from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import ScoreAdjustment, Soldier


class AdjustmentError(Exception):
    """Raised on an invalid score-adjustment operation."""


def create_adjustment(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    delta: Decimal,
    reason: str,
    duty_type_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> ScoreAdjustment:
    if session.get(Soldier, soldier_id) is None:
        raise AdjustmentError("soldier_not_found")
    if delta == 0:
        raise AdjustmentError("zero_delta")
    if not reason or not reason.strip():
        raise AdjustmentError("reason_required")
    adj = ScoreAdjustment(
        soldier_id=soldier_id,
        delta=delta,
        reason=reason,
        duty_type_id=duty_type_id,
        created_by=actor_id,
    )
    session.add(adj)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="score_adjustment.create",
        entity_type="score_adjustment",
        entity_id=adj.id,
        after={"soldier_id": str(soldier_id), "delta": str(delta)},
        context={"reason": reason},
    )
    return adj


def list_adjustments(session: Session, *, soldier_id: uuid.UUID) -> list[ScoreAdjustment]:
    return list(
        session.execute(
            select(ScoreAdjustment)
            .where(ScoreAdjustment.soldier_id == soldier_id)
            .order_by(ScoreAdjustment.created_at)
        )
        .scalars()
        .all()
    )
