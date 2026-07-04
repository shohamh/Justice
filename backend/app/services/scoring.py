from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.algorithm.duration import combine_date_time
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
from app.algorithm.duration import calendar_days_touched, score_days
from app.services.eligibility import inferred_service_type
from app.auth.authz import scope_root_ids

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
        touched = calendar_days_touched(a.start_date, a.end_date)
        day_weight = (
            Decimal(score_days(a.start_date, a.end_date, a.start_time, a.end_time)) / Decimal(touched)
            if touched > 0
            else Decimal("1")
        )
        day = a.start_date
        while day < a.end_date:
            if date_to is not None and day > date_to:
                break
            if (date_from is None or day >= date_from):
                ov = overrides.get((a.id, day))
                eff = ov.effective_soldier_id if ov is not None else a.soldier_id
                if eff is not None:
                    if a.forced_call_up_multiplier is not None:
                        mult = a.forced_call_up_multiplier
                    elif a.is_reserve:
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
                    out.append((day, eff, a.duty_type_id, mult * day_weight))
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
        last_assignment_day = a.end_date - timedelta(days=1)

        def _make_span(cur: Any, run_start: date, run_end: date) -> dict[str, Any]:
            # A run only carries the assignment's real clock time on the edge
            # day(s) that match the assignment's own boundaries; a run that
            # was split off mid-assignment by an override has no wall-clock
            # time of its own, so it degrades to a full calendar day there.
            start_time = a.start_time if run_start == a.start_date else "00:00"
            end_time = a.end_time if run_end == last_assignment_day else "23:59"
            return {
                "assignment_id": a.id,
                "soldier_id": cur,
                "duty_type_id": a.duty_type_id,
                "duty_location_id": a.duty_location_id,
                "start_date": run_start,
                # Exclusive, matching DutyAssignment/DutyShift's own convention
                # (run_end above is the run's last INCLUSIVE day).
                "end_date": run_end + timedelta(days=1),
                "start_time": start_time,
                "end_time": end_time,
                "start_at": combine_date_time(run_start, start_time),
                "end_at": combine_date_time(run_end, end_time),
                "shift_id": a.duty_shift_id,
                "is_reserve": a.is_reserve,
            }

        cur: object = _UNSET
        run_start: date | None = None
        run_end: date | None = None
        day = a.start_date
        while day < a.end_date:
            ov = overrides.get((a.id, day))
            eff = ov.effective_soldier_id if ov is not None else a.soldier_id
            if eff == cur:
                run_end = day
            else:
                if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
                    spans.append(_make_span(cur, run_start, run_end))
                cur = eff
                run_start = day if eff is not None else None
                run_end = day if eff is not None else None
            day += timedelta(days=1)
        if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
            spans.append(_make_span(cur, run_start, run_end))
    result: list[dict[str, Any]] = []
    for sp in spans:
        if soldier_ids is not None and sp["soldier_id"] not in soldier_ids:
            continue
        if date_from is not None and sp["end_date"] <= date_from:
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


def _count_exempt_days(exemptions: list, start: date, end: date) -> int:
    """Count unique exempt days in [start, end], merging overlapping ranges."""
    ranges = []
    for ex in exemptions:
        lo = max(ex.start_date, start)
        hi = min(ex.end_date, end) if ex.end_date is not None else end
        if lo <= hi:
            ranges.append((lo, hi))
    if not ranges:
        return 0
    ranges.sort()
    total = 0
    cur_lo, cur_hi = ranges[0]
    for lo, hi in ranges[1:]:
        if lo <= cur_hi + timedelta(days=1):
            cur_hi = max(cur_hi, hi)
        else:
            total += (cur_hi - cur_lo).days + 1
            cur_lo, cur_hi = lo, hi
    total += (cur_hi - cur_lo).days + 1
    return total


def _bulk_active_days(session: Session, soldiers: list[Soldier]) -> dict[uuid.UUID, int]:
    """Compute active_days for many soldiers using 3 DB queries total instead of 3-per-soldier."""
    today = date.today()
    active_dts = _active_duty_type_ids(session)
    if not active_dts:
        return {s.id: max(1, (today - s.enrolled_at).days) for s in soldiers}

    covered: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        covered[etid].add(dtid)
    full_types = {etid for etid, dts in covered.items() if active_dts <= dts}

    if not full_types:
        return {s.id: max(1, (today - s.enrolled_at).days) for s in soldiers}

    soldier_ids = [s.id for s in soldiers]
    all_exemptions = (
        session.execute(
            select(SoldierExemption).where(
                SoldierExemption.soldier_id.in_(soldier_ids),
                SoldierExemption.exemption_type_id.in_(full_types),
            )
        )
        .scalars()
        .all()
    )
    exemptions_by_soldier: dict[uuid.UUID, list] = defaultdict(list)
    for ex in all_exemptions:
        exemptions_by_soldier[ex.soldier_id].append(ex)

    result: dict[uuid.UUID, int] = {}
    for s in soldiers:
        raw = max(1, (today - s.enrolled_at).days)
        exempt_count = _count_exempt_days(exemptions_by_soldier.get(s.id, []), s.enrolled_at, today)
        result[s.id] = max(1, raw - exempt_count)
    return result


def _duty_stats_by_soldier(
    session: Session,
) -> tuple[dict[uuid.UUID, Decimal], dict[uuid.UUID, int]]:
    """Return (score_by_soldier, shift_count_by_soldier) in a single pass — half the queries of
    calling duty_score_by_soldier + shift_count_by_soldier separately."""
    type_scores = _duty_type_scores(session)
    standby_mult = _get_multiplier_setting(session, "scoring.reserve_standby_multiplier", "0.2")
    called_up_mult = _get_multiplier_setting(session, "scoring.reserve_called_up_multiplier", "1.3")
    dismissed_mult = _get_multiplier_setting(session, "scoring.dismissed_multiplier", "0.0")

    assignments = (
        session.execute(select(DutyAssignment).where(DutyAssignment.status == "published"))
        .scalars()
        .all()
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

    duty_scores: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    assignment_sets: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)

    for a in assignments:
        touched = calendar_days_touched(a.start_date, a.end_date)
        day_weight = (
            Decimal(score_days(a.start_date, a.end_date, a.start_time, a.end_time)) / Decimal(touched)
            if touched > 0
            else Decimal("1")
        )
        day = a.start_date
        while day < a.end_date:
            ov = overrides.get((a.id, day))
            eff = ov.effective_soldier_id if ov is not None else a.soldier_id
            if eff is not None:
                if a.forced_call_up_multiplier is not None:
                    mult = a.forced_call_up_multiplier
                elif a.is_reserve:
                    if (
                        a.called_up_from is not None
                        and a.called_up_to is not None
                        and a.called_up_from <= day <= a.called_up_to
                    ):
                        mult = called_up_mult
                    else:
                        mult = standby_mult
                else:
                    ranges = dismissal_ranges.get(a.id, [])
                    if any(df <= day <= dt for df, dt in ranges):
                        mult = dismissed_mult
                    else:
                        mult = Decimal("1.0")
                duty_scores[eff] += type_scores.get(a.duty_type_id, Decimal("0")) * mult * day_weight
                assignment_sets[eff].add(a.id)
            day += timedelta(days=1)

    return dict(duty_scores), {sid: len(asgns) for sid, asgns in assignment_sets.items()}


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


def _active_exemptions_by_soldier(
    session: Session,
) -> dict[uuid.UUID, list[tuple[SoldierExemption, ExemptionType]]]:
    today = date.today()
    rows = session.execute(
        select(SoldierExemption, ExemptionType)
        .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
        .where(
            SoldierExemption.start_date <= today,
            or_(
                SoldierExemption.end_date.is_(None),
                SoldierExemption.end_date >= today,
            ),
        )
    ).all()
    by_soldier: dict[uuid.UUID, list[tuple[SoldierExemption, ExemptionType]]] = defaultdict(list)
    for exemption, ex_type in rows:
        by_soldier[exemption.soldier_id].append((exemption, ex_type))
    return by_soldier


def _exemption_label(exemption: SoldierExemption, ex_type: ExemptionType) -> str:
    category = "גלובלי" if ex_type.is_global else "חלקי"
    if exemption.end_date is not None:
        return f"{ex_type.name} ({category}, עד {exemption.end_date.strftime('%d/%m/%Y')})"
    return f"{ex_type.name} ({category})"


def transparency_rows(
    session: Session, *, viewer: Soldier | None = None
) -> dict[str, Any]:
    from app.services.effort_score import compute_effort_data, quarter_start
    from app.services.settings_loader import SettingNotFound, get_setting

    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    duty_scores, shift_counts = _duty_stats_by_soldier(session)
    adj_scores = adjustments_by_soldier(session)
    active_days_map = _bulk_active_days(session, list(soldiers))
    nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    exempted_ids = globally_exempted_soldier_ids(session)
    exemptions_by_soldier = _active_exemptions_by_soldier(session)
    roots = scope_root_ids(session, viewer) if viewer is not None else set()
    can_see_exemption_aggregates = viewer is not None and (
        viewer.role == "admin" or bool(roots)
    )

    # Compute effort scores for all active soldiers
    today = date.today()
    try:
        reset_raw = get_setting(session, "fairness.reset_date")
        reset_date = date.fromisoformat(str(reset_raw))
    except (SettingNotFound, ValueError, Exception):
        reset_date = quarter_start(date(today.year - 2, today.month, 1))

    # Include future published assignments by using the day after the latest
    # published assignment as the planning horizon.  Without this, effort_score
    # is always 0 when all assignments are for upcoming dates.
    from sqlalchemy import func as sql_func
    latest_published_end = session.execute(
        select(sql_func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        planning_start = latest_published_end + timedelta(days=1)
    else:
        planning_start = today

    effort_map = compute_effort_data(
        session,
        soldiers=list(soldiers),
        planning_start=planning_start,
        planning_end=planning_start,
        reset_date=reset_date,
    )

    rows: list[dict[str, Any]] = []
    for s in soldiers:
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))
        ad = active_days_map.get(s.id, 1)
        node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        soldier_exemptions = exemptions_by_soldier.get(s.id, [])
        in_scope = node is not None and any(root in node.path_ids for root in roots)
        if in_scope:
            exemptions_display = ", ".join(
                _exemption_label(exemption, ex_type) for exemption, ex_type in soldier_exemptions
            )
        else:
            exemptions_display = "חסוי"
        has_global = any(ex_type.is_global for _, ex_type in soldier_exemptions)
        has_partial = any(not ex_type.is_global for _, ex_type in soldier_exemptions)
        has_temporary = any(exemption.end_date is not None for exemption, _ in soldier_exemptions)
        effort_data = effort_map.get(s.id)
        effort_score = float(effort_data.effort_score) if effort_data else 0.0
        c_over_d = float(effort_data.C_over_D) if effort_data else 0.0
        effort_offset_raw = effort_data.effort_offset if effort_data else 0
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
                "exemptions_display": exemptions_display,
                "exemptions_visible": in_scope,
                "has_global_exemption": has_global if can_see_exemption_aggregates else None,
                "has_partial_exemption": has_partial if can_see_exemption_aggregates else None,
                "has_temporary_exemption": has_temporary if can_see_exemption_aggregates else None,
                "effort_score": effort_score,
                "c_over_d": c_over_d,
                "effort_offset_raw": effort_offset_raw,
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
    return {"rows": rows, "can_see_exemption_aggregates": can_see_exemption_aggregates}


def soldier_score_breakdown(session: Session, *, soldier_id: uuid.UUID) -> dict[str, Any]:
    scores = _duty_type_scores(session)
    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    by_type: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    days_by_type: dict[uuid.UUID, int] = defaultdict(int)
    for _day, eff, dtid, mult in effective_duty_days(session):
        if eff == soldier_id:
            by_type[dtid] += scores.get(dtid, Decimal("0")) * mult
            days_by_type[dtid] += 1
    per_type = [
        {
            "duty_type_id": dtid,
            "duty_type_name": dt_names.get(dtid),
            "days": days_by_type[dtid],
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


def _effort_stats(values: list[float]) -> dict[str, Any] | None:
    """mean / stddev / cv / min / max for a list of effort scores (population stddev)."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    sd = var ** 0.5
    return {
        "mean": mean, "stddev": sd, "cv": (sd / mean if mean else 0.0),
        "min": min(values), "max": max(values), "count": len(values),
    }


def _build_fairness_components(
    eligible_types: dict[uuid.UUID, set[uuid.UUID]],
    type_names: dict[uuid.UUID, str],
    effort_by_id: dict[uuid.UUID, float],
    name_by_id: dict[uuid.UUID, str],
    soldier_eligible_types: dict[uuid.UUID, set[uuid.UUID]] | None = None,
) -> dict[str, Any]:
    """Group soldiers into connected components of the soldier↔duty-type eligibility
    graph: two soldiers connect if they share a doable duty type (transitively).
    Soldiers eligible for no active type go in the 'exempt_from_all' bucket. Each
    component reports the duty types that connect it and its effort spread (פיזור)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    exempt_all: list[uuid.UUID] = []
    for sid, elig in eligible_types.items():
        if not elig:
            exempt_all.append(sid)
            continue
        snode = f"s:{sid}"
        find(snode)
        for tid in elig:
            union(snode, f"t:{tid}")

    groups: dict[str, dict[str, Any]] = {}
    for sid, elig in eligible_types.items():
        if not elig:
            continue
        g = groups.setdefault(find(f"s:{sid}"), {"soldiers": [], "type_ids": set()})
        g["soldiers"].append(sid)
        g["type_ids"].update(elig)

    elig = soldier_eligible_types or eligible_types

    def soldier_obj(sid: uuid.UUID, component_type_ids: set[uuid.UUID] | None = None) -> dict[str, Any]:
        eligible_count = len(elig.get(sid, set()) & component_type_ids) if component_type_ids is not None else 0
        return {"soldier_id": sid, "full_name": name_by_id.get(sid, ""),
                "effort_score": effort_by_id.get(sid, 0.0),
                "eligible_type_count": eligible_count}

    components = []
    for g in groups.values():
        effs = [effort_by_id.get(sid, 0.0) for sid in g["soldiers"]]
        comp_type_ids: set[uuid.UUID] = g["type_ids"]
        components.append({
            "duty_type_names": sorted(type_names[tid] for tid in comp_type_ids if tid in type_names),
            "soldier_count": len(g["soldiers"]),
            "effort": _effort_stats(effs),
            "soldiers": sorted((soldier_obj(s, comp_type_ids) for s in g["soldiers"]),
                               key=lambda o: o["effort_score"], reverse=True),
        })
    components.sort(key=lambda c: c["soldier_count"], reverse=True)

    return {
        "exempt_from_all": {
            "count": len(exempt_all),
            "soldiers": sorted((soldier_obj(s) for s in exempt_all),
                               key=lambda o: o["full_name"]),
        },
        "components": components,
    }


def fairness_components(session: Session) -> dict[str, Any]:
    """Effort spread (פיזור) split by connected components of soldiers who share
    duty-type eligibility, plus the soldiers exempt from every active duty type."""
    from app.services.algorithm_bridge import load_soldier_inputs

    rows = transparency_rows(session)["rows"]
    effort_by_id = {r["soldier_id"]: float(r["effort_score"]) for r in rows}
    name_by_id = {r["soldier_id"]: r["full_name"] for r in rows}

    active_type_ids = _active_duty_type_ids(session)
    type_names = {
        dt.id: dt.name
        for dt in session.execute(
            select(DutyType).where(DutyType.id.in_(active_type_ids))
        ).scalars().all()
    }
    inputs = load_soldier_inputs(session, as_of=date.today())
    eligible_types = {
        si.id: (active_type_ids - set(si.exempted_duty_type_ids)) for si in inputs
    }
    return _build_fairness_components(eligible_types, type_names, effort_by_id, name_by_id, soldier_eligible_types=eligible_types)
