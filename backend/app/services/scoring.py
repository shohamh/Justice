from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyDismissal,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    ScoreAdjustment,
    Soldier,
    SoldierExemption,
)
from app.services.eligibility import inferred_service_type

_UNSET: object = object()


def _duty_type_scores(session: Session) -> dict[uuid.UUID, Decimal]:
    return {dt.id: dt.score_per_day for dt in session.execute(select(DutyType)).scalars().all()}


def _get_multiplier_setting(session: Session, key: str, default: str) -> Decimal:
    from app.services.settings_loader import SettingNotFound, get_setting
    try:
        return Decimal(str(get_setting(session, key)))
    except SettingNotFound:
        return Decimal(default)


def effective_duty_days(
    session: Session, *, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[date, uuid.UUID, uuid.UUID, Decimal]]:
    """Expand every published assignment to (date, effective_soldier_id, duty_type_id, multiplier).

    Multiplier depends on:
    - Primary assignment: 1.0, or dismissed_multiplier if a DutyDismissal covers that day
    - Reserve assignment: called_up_multiplier if in called-up range, else standby_multiplier
    Overrides (replacements) still reassign effective_soldier_id.
    """
    standby_mult = _get_multiplier_setting(session, "scoring.reserve_standby_multiplier", "0.2")
    called_up_mult = _get_multiplier_setting(session, "scoring.reserve_called_up_multiplier", "1.3")
    dismissed_mult = _get_multiplier_setting(session, "scoring.dismissed_multiplier", "0.0")

    assignments = (
        session.execute(select(DutyAssignment).where(DutyAssignment.status == "published"))
        .scalars().all()
    )
    overrides = {
        (o.duty_assignment_id, o.date): o
        for o in session.execute(select(DutyDayOverride)).scalars().all()
    }
    dismissal_ranges: dict[uuid.UUID, list[tuple[date, date]]] = {}
    for d in session.execute(select(DutyDismissal)).scalars().all():
        dismissal_ranges.setdefault(d.duty_assignment_id, []).append(
            (d.dismissed_from, d.dismissed_to)
        )

    out: list[tuple[date, uuid.UUID, uuid.UUID, Decimal]] = []
    for a in assignments:
        day = a.start_date
        while day <= a.end_date:
            if date_to is not None and day > date_to:
                break
            if (date_from is None or day >= date_from):
                ov = overrides.get((a.id, day))
                eff = ov.effective_soldier_id if ov is not None else a.soldier_id
                if eff is not None:
                    if a.is_reserve:
                        if (a.called_up_from is not None and a.called_up_to is not None
                                and a.called_up_from <= day <= a.called_up_to):
                            mult = called_up_mult
                        else:
                            mult = standby_mult
                    else:
                        ranges = dismissal_ranges.get(a.id, [])
                        if any(df <= day <= dt for df, dt in ranges):
                            mult = dismissed_mult
                        else:
                            mult = Decimal("1.0")
                    out.append((day, eff, a.duty_type_id, mult))
            day += timedelta(days=1)
    return out


def effective_duty_spans(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Published assignments expanded per day with overrides applied, then re-merged into
    contiguous runs where the effective soldier is unchanged. Degrades to the original block
    when there are no overrides; cancelled days (NULL effective) break runs and are dropped.
    Optionally filtered to soldier_ids and to spans overlapping [date_from, date_to]."""
    assignments = (
        session.execute(select(DutyAssignment).where(DutyAssignment.status == "published"))
        .scalars()
        .all()
    )
    overrides = {
        (o.duty_assignment_id, o.date): o
        for o in session.execute(select(DutyDayOverride)).scalars().all()
    }
    spans: list[dict[str, Any]] = []
    for a in assignments:
        cur: object = _UNSET
        run_start: date | None = None
        run_end: date | None = None
        day = a.start_date
        while day <= a.end_date:
            ov = overrides.get((a.id, day))
            eff = ov.effective_soldier_id if ov is not None else a.soldier_id
            if eff == cur:
                run_end = day
            else:
                if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
                    spans.append(
                        {
                            "assignment_id": a.id,
                            "soldier_id": cur,
                            "duty_type_id": a.duty_type_id,
                            "duty_location_id": a.duty_location_id,
                            "start_date": run_start,
                            "end_date": run_end,
                        }
                    )
                cur = eff
                run_start = day if eff is not None else None
                run_end = day if eff is not None else None
            day += timedelta(days=1)
        if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
            spans.append(
                {
                    "assignment_id": a.id,
                    "soldier_id": cur,
                    "duty_type_id": a.duty_type_id,
                    "duty_location_id": a.duty_location_id,
                    "start_date": run_start,
                    "end_date": run_end,
                }
            )
    result: list[dict[str, Any]] = []
    for sp in spans:
        if soldier_ids is not None and sp["soldier_id"] not in soldier_ids:
            continue
        if date_from is not None and sp["end_date"] < date_from:
            continue
        if date_to is not None and sp["start_date"] > date_to:
            continue
        result.append(sp)
    result.sort(key=lambda s: s["start_date"])
    return result


def shift_count_by_soldier(session: Session) -> dict[uuid.UUID, int]:
    """Count distinct published assignments per effective soldier (ignoring duration)."""
    counts: dict[uuid.UUID, set] = defaultdict(set)
    for sp in effective_duty_spans(session):
        counts[sp["soldier_id"]].add(sp["assignment_id"])
    return {s_id: len(asgns) for s_id, asgns in counts.items()}


def duty_score_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    scores = _duty_type_scores(session)
    out: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for _day, eff, dtid, mult in effective_duty_days(session):
        out[eff] += scores.get(dtid, Decimal("0")) * mult
    return out


def adjustments_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    rows = session.execute(
        select(ScoreAdjustment.soldier_id, func.sum(ScoreAdjustment.delta)).group_by(
            ScoreAdjustment.soldier_id
        )
    ).all()
    return {sid: Decimal(total) for sid, total in rows}


def cumulative_score(session: Session, *, soldier_id: uuid.UUID) -> Decimal:
    duty = duty_score_by_soldier(session).get(soldier_id, Decimal("0"))
    adj = adjustments_by_soldier(session).get(soldier_id, Decimal("0"))
    return duty + adj


def _active_duty_type_ids(session: Session) -> set[uuid.UUID]:
    return set(
        session.execute(select(DutyType.id).where(DutyType.active.is_(True))).scalars().all()
    )


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
    exemptions = (
        session.execute(
            select(SoldierExemption).where(
                SoldierExemption.soldier_id == soldier_id,
                SoldierExemption.exemption_type_id.in_(full_types),
            )
        )
        .scalars()
        .all()
    )
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
    return cumulative_score(session, soldier_id=soldier.id) / Decimal(
        active_days(session, soldier=soldier)
    )


def globally_exempted_soldier_ids(session: Session) -> set[uuid.UUID]:
    """Return the set of soldier IDs who have an active global exemption today."""
    today = date.today()
    exemptions = (
        session.execute(
            select(SoldierExemption)
            .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
            .where(
                ExemptionType.is_global.is_(True),
                SoldierExemption.start_date <= today,
                or_(
                    SoldierExemption.end_date.is_(None),
                    SoldierExemption.end_date >= today,
                ),
            )
        )
        .scalars()
        .all()
    )
    return {ex.soldier_id for ex in exemptions}


def transparency_rows(session: Session) -> list[dict[str, Any]]:
    from app.services.effort_score import compute_effort_data, quarter_start
    from app.services.settings_loader import SettingNotFound, get_setting

    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    duty_scores = duty_score_by_soldier(session)
    adj_scores = adjustments_by_soldier(session)
    shift_counts = shift_count_by_soldier(session)
    nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    exempted_ids = globally_exempted_soldier_ids(session)

    # Compute effort scores for all active soldiers
    today = date.today()
    try:
        reset_raw = get_setting(session, "fairness.reset_date")
        reset_date = date.fromisoformat(str(reset_raw))
    except (SettingNotFound, ValueError, Exception):
        reset_date = quarter_start(date(today.year - 2, today.month, 1))

    effort_map = compute_effort_data(
        session,
        soldiers=list(soldiers),
        planning_start=today,
        planning_end=today,
        reset_date=reset_date,
    )

    rows: list[dict[str, Any]] = []
    for s in soldiers:
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))
        ad = active_days(session, soldier=s)
        node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        effort_data = effort_map.get(s.id)
        effort_score = float(effort_data.effort_score) if effort_data else 0.0
        rows.append(
            {
                "soldier_id": s.id,
                "full_name": s.full_name,
                "node_id": s.hierarchy_node_id,
                "node_name": node.name if node is not None else None,
                "enrolled_at": s.enrolled_at,
                "active_days": ad,
                "shift_count": shift_counts.get(s.id, 0),
                "rank": s.rank,
                "is_officer": s.is_officer,
                "service_type": inferred_service_type(s),
                "cumulative_score": cum,
                "score_per_day": cum / Decimal(ad),
                "is_globally_exempted": s.id in exempted_ids,
                "effort_score": effort_score,
            }
        )
    if rows:
        avg_spd = sum(r["score_per_day"] for r in rows) / Decimal(len(rows))
    else:
        avg_spd = Decimal("0")
    for r in rows:
        r["normalised_score"] = (
            r["score_per_day"] / avg_spd if avg_spd != Decimal("0") else Decimal("0")
        )
    rows.sort(key=lambda r: r["effort_score"], reverse=True)
    return rows


def soldier_score_breakdown(session: Session, *, soldier_id: uuid.UUID) -> dict[str, Any]:
    scores = _duty_type_scores(session)
    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    by_type: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for _day, eff, dtid, mult in effective_duty_days(session):
        if eff == soldier_id:
            by_type[dtid] += scores.get(dtid, Decimal("0")) * mult
    per_type = [
        {
            "duty_type_id": dtid,
            "duty_type_name": dt_names.get(dtid),
            "score": score,
        }
        for dtid, score in by_type.items()
    ]
    adjustments = (
        session.execute(
            select(ScoreAdjustment)
            .where(ScoreAdjustment.soldier_id == soldier_id)
            .order_by(ScoreAdjustment.created_at)
        )
        .scalars()
        .all()
    )
    return {"per_type": per_type, "adjustments": list(adjustments)}
