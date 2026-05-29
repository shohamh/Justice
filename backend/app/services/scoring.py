from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyType,
    ExemptionDutyTypeMap,
    HierarchyNode,
    ScoreAdjustment,
    Soldier,
    SoldierExemption,
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


def _active_duty_type_ids(session: Session) -> set[uuid.UUID]:
    return set(session.execute(
        select(DutyType.id).where(DutyType.active.is_(True))
    ).scalars().all())


def _full_coverage_exempt_dates(
    session: Session, *, soldier_id: uuid.UUID, start: date, end: date
) -> set[date]:
    active_dts = _active_duty_type_ids(session)
    if not active_dts:
        return set()  # no active duty types => "full coverage" undefined; subtract nothing
    covered: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        covered[etid].add(dtid)
    full_types = {etid for etid, dts in covered.items() if active_dts <= dts}
    if not full_types:
        return set()
    result: set[date] = set()
    exemptions = session.execute(
        select(SoldierExemption).where(
            SoldierExemption.soldier_id == soldier_id,
            SoldierExemption.exemption_type_id.in_(full_types),
        )
    ).scalars().all()
    for ex in exemptions:
        lo = max(ex.start_date, start)
        hi = min(ex.end_date, end) if ex.end_date is not None else end
        day = lo
        while day <= hi:
            result.add(day)
            day += timedelta(days=1)
    return result


def active_days(session: Session, *, soldier: Soldier) -> int:
    today = date.today()
    raw = (today - soldier.enrolled_at).days
    if raw < 1:
        raw = 1  # why: avoid divide-by-zero for same-day enrolment
    exempt = _full_coverage_exempt_dates(
        session, soldier_id=soldier.id, start=soldier.enrolled_at, end=today
    )
    return max(1, raw - len(exempt))


def normalised_score(session: Session, *, soldier: Soldier) -> Decimal:
    return cumulative_score(session, soldier_id=soldier.id) / Decimal(active_days(session, soldier=soldier))


def transparency_rows(session: Session) -> list[dict[str, Any]]:
    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    duty_scores = duty_score_by_soldier(session)
    adj_scores = adjustments_by_soldier(session)
    nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    rows: list[dict[str, Any]] = []
    for s in soldiers:
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))
        ad = active_days(session, soldier=s)
        node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        rows.append({
            "soldier_id": s.id,
            "full_name": s.full_name,
            "node_name": node.name if node is not None else None,
            "enrolled_at": s.enrolled_at,
            "active_days": ad,
            "cumulative_score": cum,
            "normalised_score": cum / Decimal(ad),
        })
    rows.sort(key=lambda r: r["normalised_score"], reverse=True)
    return rows


def soldier_score_breakdown(session: Session, *, soldier_id: uuid.UUID) -> dict[str, Any]:
    scores = _duty_type_scores(session)
    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    by_type_days: dict[uuid.UUID, int] = defaultdict(int)
    for _day, eff, dtid in effective_duty_days(session):
        if eff == soldier_id:
            by_type_days[dtid] += 1
    per_type = [
        {"duty_type_id": dtid, "duty_type_name": dt_names.get(dtid), "days": days,
         "score": scores.get(dtid, Decimal("0")) * days}
        for dtid, days in by_type_days.items()
    ]
    adjustments = session.execute(
        select(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier_id)
        .order_by(ScoreAdjustment.created_at)
    ).scalars().all()
    return {"per_type": per_type, "adjustments": list(adjustments)}
