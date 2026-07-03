from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, median, stdev

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyShift,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    HierarchyNode,
    ScoreAdjustment,
    Soldier,
    SoldierExemption,
    SoldierFieldUpdate,
    SwapRequest,
)


def _soldiers_in_nodes(session: Session, subtree_ids: list[uuid.UUID]) -> list[Soldier]:
    return (
        session.execute(
            select(Soldier).where(
                Soldier.hierarchy_node_id.in_(subtree_ids),
                Soldier.left_at.is_(None),
            )
        )
        .scalars()
        .all()
    )


def _score_data(session: Session, soldiers: list[Soldier]) -> dict[uuid.UUID, dict]:
    soldier_ids = {s.id for s in soldiers}
    duty_scores: dict[uuid.UUID, Decimal] = {}
    for dt in session.execute(select(DutyType)).scalars().all():
        duty_scores[dt.id] = dt.score_per_day

    score_by_soldier: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.soldier_id.in_(soldier_ids),
            )
        )
        .scalars()
        .all()
    )
    for a in assignments:
        days = (a.end_date - a.start_date).days
        score_by_soldier[a.soldier_id] += duty_scores.get(a.duty_type_id, Decimal("0")) * Decimal(
            days
        )

    adj_totals: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in session.execute(
        select(ScoreAdjustment.soldier_id, func.sum(ScoreAdjustment.delta))
        .where(ScoreAdjustment.soldier_id.in_(soldier_ids))
        .group_by(ScoreAdjustment.soldier_id)
    ).all():
        adj_totals[row[0]] += Decimal(row[1])

    result: dict[uuid.UUID, dict] = {}
    today = date.today()
    for s in soldiers:
        cum = score_by_soldier.get(s.id, Decimal("0")) + adj_totals.get(s.id, Decimal("0"))
        raw_days = (today - s.enrolled_at).days
        ad = max(1, raw_days)
        result[s.id] = {
            "cumulative_score": cum,
            "normalised_score": cum / Decimal(ad),
            "active_days": ad,
        }
    return result


def summary_cards(session: Session, *, subtree_ids: list[uuid.UUID]) -> dict:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    soldier_ids = {s.id for s in soldiers}

    # Approvals: pending field updates + exemption requests + swap approvals
    pending_field = (
        session.execute(
            select(func.count(SoldierFieldUpdate.id)).where(
                SoldierFieldUpdate.soldier_id.in_(soldier_ids),
                SoldierFieldUpdate.status == "pending",
            )
        ).scalar()
        or 0
    )

    pending_exempt = (
        session.execute(
            select(func.count(ExemptionRequest.id)).where(
                ExemptionRequest.soldier_id.in_(soldier_ids),
                ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
            )
        ).scalar()
        or 0
    )

    pending_swaps = (
        session.execute(
            select(func.count(SwapRequest.id)).where(
                SwapRequest.requesting_soldier_id.in_(soldier_ids),
                SwapRequest.status == "pending",
            )
        ).scalar()
        or 0
    )

    approvals_pending = pending_field + pending_exempt + pending_swaps

    # Upcoming duties in next 7 days
    today = date.today()
    next_week = today + timedelta(days=7)
    upcoming_assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.start_date <= next_week,
                DutyAssignment.end_date > today,
            )
        )
        .scalars()
        .all()
    )
    upcoming_duties_7d = len(upcoming_assignments)

    # Unfilled gaps: shifts in the commander's subtree with fill_status != "full"
    shifts_in_subtree = (
        session.execute(
            select(DutyShift).where(
                DutyShift.duty_type_id.in_(select(DutyType.id).where(DutyType.active.is_(True)))
            )
        )
        .scalars()
        .all()
    )

    unfilled_gaps = 0
    for shift in shifts_in_subtree:
        if shift.start_date <= next_week and shift.end_date > today:
            assigned = (
                session.execute(
                    select(func.count(DutyAssignment.id)).where(
                        DutyAssignment.duty_shift_id == shift.id,
                        DutyAssignment.status == "published",
                    )
                ).scalar()
                or 0
            )
            if assigned < shift.required_count:
                unfilled_gaps += 1

    # Alerts: soldiers below score threshold, exemptions expiring
    score_data = _score_data(session, soldiers)
    threshold = Decimal("-3.0")
    alerts_count = sum(1 for sd in score_data.values() if sd["normalised_score"] < threshold)

    # Exemptions expiring within 7 days
    for s in soldiers:
        expiring = (
            session.execute(
                select(func.count(SoldierExemption.id)).where(
                    SoldierExemption.soldier_id == s.id,
                    SoldierExemption.end_date.isnot(None),
                    SoldierExemption.end_date <= next_week,
                    SoldierExemption.end_date >= today,
                )
            ).scalar()
            or 0
        )
        alerts_count += expiring

    return {
        "approvals_pending": approvals_pending,
        "upcoming_duties_7d": upcoming_duties_7d,
        "unfilled_gaps": unfilled_gaps,
        "alerts_count": alerts_count,
    }


def soldiers_in_subtree(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    score_data = _score_data(session, soldiers)

    # Compute status
    today = date.today()
    result = []
    for s in soldiers:
        status = "active"
        # Check for active global exemptions
        ex = (
            session.execute(
                select(SoldierExemption).where(
                    SoldierExemption.soldier_id == s.id,
                    SoldierExemption.start_date <= today,
                    (SoldierExemption.end_date.is_(None) | (SoldierExemption.end_date >= today)),
                )
            )
            .scalars()
            .all()
        )
        if ex:
            for e in ex:
                et = session.get(ExemptionType, e.exemption_type_id)
                if et and et.is_global:
                    status = "exempt"
                    break

        sd = score_data.get(
            s.id, {"cumulative_score": Decimal("0"), "normalised_score": Decimal("0")}
        )
        result.append(
            {
                "id": s.id,
                "personal_number": s.personal_number,
                "full_name": s.full_name,
                "role": s.role,
                "hierarchy_node_id": s.hierarchy_node_id,
                "status": status,
                "cumulative_score": sd["cumulative_score"],
                "normalised_score": sd["normalised_score"],
                "enrolled_at": s.enrolled_at,
                "left_at": s.left_at,
            }
        )
    return result


def fairness_stats(session: Session, *, subtree_ids: list[uuid.UUID]) -> dict:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    score_data = _score_data(session, soldiers)
    scores = [float(sd["normalised_score"]) for sd in score_data.values()]
    if not scores:
        return {
            "mean": 0.0,
            "median": 0.0,
            "min": 0.0,
            "max": 0.0,
            "stddev": 0.0,
            "soldier_count": 0,
        }
    return {
        "mean": round(mean(scores), 4),
        "median": round(median(scores), 4),
        "min": round(min(scores), 4),
        "max": round(max(scores), 4),
        "stddev": round(stdev(scores), 4) if len(scores) > 1 else 0.0,
        "soldier_count": len(scores),
    }


def potential_counts(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    total_soldiers = len(soldiers)

    counts: list[dict] = []
    chova = sum(1 for s in soldiers if s.mandatory_end_date and s.mandatory_end_date > date.today())
    counts.append({"label": "חובה", "count": chova, "unit_total": None})
    keva = sum(1 for s in soldiers if s.rank and s.rank in ("sgan_aluf", "rav_saren", "saren"))
    counts.append({"label": "קבע", "count": keva, "unit_total": None})
    bahad1 = sum(1 for s in soldiers if s.bahad1_graduate)
    counts.append({"label": 'בוגרי בה"ד 1', "count": bahad1, "unit_total": None})
    officers = sum(1 for s in soldiers if s.is_officer)
    counts.append({"label": "קצינים", "count": officers, "unit_total": None})
    counts.append({"label": 'סה"כ חיילים', "count": total_soldiers, "unit_total": None})
    return counts


def upcoming_duties(session: Session, *, subtree_ids: list[uuid.UUID], days: int) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    soldier_ids = {s.id for s in soldiers}
    today = date.today()
    end = today + timedelta(days=days)

    assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status == "published",
                DutyAssignment.soldier_id.in_(soldier_ids),
                DutyAssignment.start_date <= end,
                DutyAssignment.end_date >= today,
            )
        )
        .scalars()
        .all()
    )

    day_map: dict[date, list[dict]] = {}
    d = today
    while d <= end:
        day_map[d] = []
        d += timedelta(days=1)

    # Preload lookup maps
    soldier_map = {s.id: s for s in soldiers}
    duty_type_rows = session.execute(select(DutyType)).scalars().all()
    duty_type_map = {dt.id: dt for dt in duty_type_rows}
    node_rows = session.execute(select(HierarchyNode)).scalars().all()
    node_map = {n.id: n for n in node_rows}

    for a in assignments:
        d = max(a.start_date, today)
        soldier = soldier_map.get(a.soldier_id)
        dt = duty_type_map.get(a.duty_type_id)
        node = node_map.get(soldier.hierarchy_node_id) if soldier else None
        while d < min(a.end_date, end + timedelta(days=1)):
            day_map.setdefault(d, []).append(
                {
                    "assignment_id": str(a.id),
                    "soldier_id": str(a.soldier_id),
                    "soldier_name": soldier.full_name if soldier else "",
                    "duty_type_id": str(a.duty_type_id),
                    "duty_type_name": dt.name if dt else "",
                    "node_name": node.name if node else "",
                    "is_reserve": a.is_reserve,
                }
            )
            d += timedelta(days=1)

    result = []
    for dt, assigns in sorted(day_map.items()):
        result.append({"date": str(dt), "assignments": assigns})
    return result


def alerts(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    score_data = _score_data(session, soldiers)
    threshold = Decimal("-3.0")
    today = date.today()
    next_week = today + timedelta(days=7)

    alerts_list: list[dict] = []

    for s in soldiers:
        sd = score_data.get(s.id, {})
        norm = sd.get("normalised_score", Decimal("0"))
        if norm < threshold:
            alerts_list.append(
                {
                    "severity": "warning",
                    "soldier_id": s.id,
                    "soldier_name": s.full_name,
                    "message": f"ניקוד מנורמל נמוך: {norm:.2f}",
                }
            )

        exemptions = (
            session.execute(
                select(SoldierExemption).where(
                    SoldierExemption.soldier_id == s.id,
                    SoldierExemption.end_date.isnot(None),
                    SoldierExemption.end_date <= next_week,
                    SoldierExemption.end_date >= today,
                )
            )
            .scalars()
            .all()
        )
        for ex in exemptions:
            et = session.get(ExemptionType, ex.exemption_type_id)
            name = et.name if et else "פטור"
            alerts_list.append(
                {
                    "severity": "info",
                    "soldier_id": s.id,
                    "soldier_name": s.full_name,
                    "message": f"תוקף {name} מסתיים ב-{ex.end_date}",
                }
            )

    return alerts_list


def pending_approvals(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    soldier_ids = {s.id for s in soldiers}
    name_map = {s.id: s.full_name for s in soldiers}

    items: list[dict] = []

    # Field updates
    fus = (
        session.execute(
            select(SoldierFieldUpdate).where(
                SoldierFieldUpdate.soldier_id.in_(soldier_ids),
                SoldierFieldUpdate.status == "pending",
            )
        )
        .scalars()
        .all()
    )
    for fu in fus:
        items.append(
            {
                "id": fu.id,
                "soldier_id": fu.soldier_id,
                "soldier_name": name_map.get(fu.soldier_id, ""),
                "request_type": "field_update",
                "summary": f"שינוי {fu.field_name}: {fu.previous_value or 'ריק'} → {fu.new_value}",
                "created_at": str(fu.created_at),
            }
        )

    # Exemption requests
    ers = (
        session.execute(
            select(ExemptionRequest).where(
                ExemptionRequest.soldier_id.in_(soldier_ids),
                ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
            )
        )
        .scalars()
        .all()
    )
    for er in ers:
        items.append(
            {
                "id": er.id,
                "soldier_id": er.soldier_id,
                "soldier_name": name_map.get(er.soldier_id, ""),
                "request_type": "exemption",
                "summary": "בקשת פטור",
                "created_at": str(er.created_at),
            }
        )

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items
