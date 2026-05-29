from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyType,
    ScoreAdjustment,
)


def _duty_type_scores(session: Session) -> dict[uuid.UUID, Decimal]:
    return {dt.id: dt.score_per_day for dt in session.execute(select(DutyType)).scalars().all()}


def effective_duty_days(
    session: Session, *, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[date, uuid.UUID, uuid.UUID]]:
    """Expand every published assignment to (date, effective_soldier_id, duty_type_id) tuples,
    applying overrides (replacement reassigns; NULL effective drops the day)."""
    assignments = session.execute(
        select(DutyAssignment).where(DutyAssignment.status == "published")
    ).scalars().all()
    overrides = {
        (o.duty_assignment_id, o.date): o
        for o in session.execute(select(DutyDayOverride)).scalars().all()
    }
    out: list[tuple[date, uuid.UUID, uuid.UUID]] = []
    for a in assignments:
        day = a.start_date
        while day <= a.end_date:
            if (date_from is None or day >= date_from) and (date_to is None or day <= date_to):
                ov = overrides.get((a.id, day))
                eff = ov.effective_soldier_id if ov is not None else a.soldier_id
                if eff is not None:
                    out.append((day, eff, a.duty_type_id))
            day += timedelta(days=1)
    return out


def duty_score_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    scores = _duty_type_scores(session)
    out: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for _day, eff, dtid in effective_duty_days(session):
        out[eff] += scores.get(dtid, Decimal("0"))
    return out


def adjustments_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    rows = session.execute(
        select(ScoreAdjustment.soldier_id, func.sum(ScoreAdjustment.delta))
        .group_by(ScoreAdjustment.soldier_id)
    ).all()
    return {sid: Decimal(total) for sid, total in rows}


def cumulative_score(session: Session, *, soldier_id: uuid.UUID) -> Decimal:
    duty = duty_score_by_soldier(session).get(soldier_id, Decimal("0"))
    adj = adjustments_by_soldier(session).get(soldier_id, Decimal("0"))
    return duty + adj
