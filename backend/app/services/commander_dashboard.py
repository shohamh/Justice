from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, median, stdev
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    HierarchyNode,
    Soldier,
    SoldierExemption,
    SoldierFieldUpdate,
    SwapCandidate,
    SwapRequest,
)
from app.services.score_projection import commander_alert_warning_scores, commander_score_totals
from app.services.sql_arrays import uuid_any


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


def _active_global_exemption_soldier_ids(
    session: Session, soldier_ids: set[uuid.UUID], *, as_of: date
) -> set[uuid.UUID]:
    """Soldier ids with a currently-active global exemption, in one query."""
    if not soldier_ids:
        return set()
    rows = session.execute(
        select(SoldierExemption.soldier_id)
        .join(ExemptionType, ExemptionType.id == SoldierExemption.exemption_type_id)
        .where(
            uuid_any("soldier_exemptions.soldier_id", soldier_ids),
            ExemptionType.is_global.is_(True),
            SoldierExemption.start_date <= as_of,
            (SoldierExemption.end_date.is_(None) | (SoldierExemption.end_date >= as_of)),
        )
    ).all()
    return {row[0] for row in rows}


def _soon_expiring_exemptions(
    session: Session,
    soldier_ids: set[uuid.UUID],
    *,
    start: date,
    end: date,
    soldier_id_scope: Select[Any] | None = None,
) -> list[tuple[uuid.UUID, date, str]]:
    """(soldier_id, end_date, exemption_type_name) for exemptions expiring in [start, end], in one query.

    ``soldier_id_scope``, when given, is a ``SELECT`` of exactly ``soldier_ids``
    and replaces the id array parameter (see ``commander_alert_warning_scores``).
    """
    if not soldier_ids:
        return []
    soldier_filter = (
        SoldierExemption.soldier_id.in_(soldier_id_scope)
        if soldier_id_scope is not None
        else uuid_any("soldier_exemptions.soldier_id", soldier_ids)
    )
    rows = session.execute(
        select(SoldierExemption.soldier_id, SoldierExemption.end_date, ExemptionType.name)
        .join(ExemptionType, ExemptionType.id == SoldierExemption.exemption_type_id)
        .where(
            soldier_filter,
            SoldierExemption.revoked_at.is_(None),
            SoldierExemption.end_date.isnot(None),
            SoldierExemption.end_date <= end,
            SoldierExemption.end_date >= start,
        )
    ).all()
    return [(row[0], row[1], row[2]) for row in rows]


def _score_data(session: Session, soldiers: list[Soldier]) -> dict[uuid.UUID, dict]:
    score_by_soldier = commander_score_totals(session, soldiers=soldiers).score_by_soldier
    result: dict[uuid.UUID, dict] = {}
    today = date.today()
    for s in soldiers:
        cum = score_by_soldier.get(s.id, Decimal("0"))
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
                uuid_any("soldier_field_updates.soldier_id", soldier_ids),
                SoldierFieldUpdate.status == "pending",
            )
        ).scalar()
        or 0
    )

    pending_exempt = (
        session.execute(
            select(func.count(ExemptionRequest.id)).where(
                uuid_any("exemption_requests.soldier_id", soldier_ids),
                ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
            )
        ).scalar()
        or 0
    )

    # A swap is "mid manager-approval" once it has at least one live
    # (pending/accepted) SwapCandidate — mirrors list_pending_approval in
    # app.services.swaps, since SwapRequest.status no longer has a
    # "pending_approval" value of its own (that state now lives on the
    # candidate rows).
    _swap_candidate_request_ids = (
        session.execute(
            select(SwapCandidate.swap_request_id)
            .where(SwapCandidate.status.in_(["pending", "accepted"]))
            .distinct()
        )
        .scalars()
        .all()
    )
    pending_swaps = (
        (
            session.execute(
                select(func.count(SwapRequest.id)).where(
                    uuid_any("swap_requests.requesting_soldier_id", soldier_ids),
                    SwapRequest.status == "open",
                    SwapRequest.id.in_(_swap_candidate_request_ids),
                )
            ).scalar()
            or 0
        )
        if _swap_candidate_request_ids
        else 0
    )

    approvals_pending = pending_field + pending_exempt + pending_swaps

    # Upcoming duties in next 7 days
    today = date.today()
    next_week = today + timedelta(days=7)
    upcoming_assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
                uuid_any("duty_assignments.soldier_id", soldier_ids),
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

    shifts_in_window = [
        shift
        for shift in shifts_in_subtree
        if shift.start_date <= next_week and shift.end_date > today
    ]
    assigned_by_shift = (
        {
            shift_id: count
            for shift_id, count in session.execute(
                select(DutyAssignment.duty_shift_id, func.count(DutyAssignment.id))
                .where(
                    DutyAssignment.duty_shift_id.in_([shift.id for shift in shifts_in_window]),
                    DutyAssignment.status == "published",
                )
                .group_by(DutyAssignment.duty_shift_id)
            ).all()
        }
        if shifts_in_window
        else {}
    )
    unfilled_gaps = sum(
        assigned_by_shift.get(shift.id, 0) < shift.required_count for shift in shifts_in_window
    )
    # Alerts: soldiers below score threshold, exemptions expiring
    score_data = _score_data(session, soldiers)
    threshold = Decimal("-3.0")
    alerts_count = sum(1 for sd in score_data.values() if sd["normalised_score"] < threshold)

    # Exemptions expiring within 7 days, counted in one grouped query.
    expiring_count = (
        session.execute(
            select(func.count(SoldierExemption.id)).where(
                uuid_any("soldier_exemptions.soldier_id", soldier_ids),
                SoldierExemption.end_date.isnot(None),
                SoldierExemption.end_date <= next_week,
                SoldierExemption.end_date >= today,
            )
        ).scalar()
        or 0
    )
    alerts_count += expiring_count
    return {
        "approvals_pending": approvals_pending,
        "upcoming_duties_7d": upcoming_duties_7d,
        "unfilled_gaps": unfilled_gaps,
        "alerts_count": alerts_count,
    }


def soldiers_in_subtree(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    soldiers = _soldiers_in_nodes(session, subtree_ids)
    score_data = _score_data(session, soldiers)

    today = date.today()
    soldier_ids = {s.id for s in soldiers}
    exempt_soldier_ids = _active_global_exemption_soldier_ids(session, soldier_ids, as_of=today)

    result = []
    for s in soldiers:
        status = "exempt" if s.id in exempt_soldier_ids else "active"

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
    chova = keva = bahad1 = officers = total_soldiers = 0
    if subtree_ids:
        chova, keva, bahad1, officers, total_soldiers = session.execute(
            select(
                func.sum(case((Soldier.mandatory_end_date > date.today(), 1), else_=0)),
                func.sum(case((Soldier.rank.in_(("sgan_aluf", "rav_saren", "saren")), 1), else_=0)),
                func.sum(case((Soldier.bahad1_graduate.is_(True), 1), else_=0)),
                func.sum(case((Soldier.is_officer.is_(True), 1), else_=0)),
                func.count(Soldier.id),
            ).where(Soldier.hierarchy_node_id.in_(subtree_ids), Soldier.left_at.is_(None))
        ).one()
        chova, keva, bahad1, officers = (
            chova or 0, keva or 0, bahad1 or 0, officers or 0
        )

    counts: list[dict] = []
    counts.append({"label": "חובה", "count": chova, "unit_total": None})
    counts.append({"label": "קבע", "count": keva, "unit_total": None})
    counts.append({"label": 'בוגרי בה"ד 1', "count": bahad1, "unit_total": None})
    counts.append({"label": "קצינים", "count": officers, "unit_total": None})
    counts.append({"label": 'סה"כ חיילים', "count": total_soldiers, "unit_total": None})
    return counts


def upcoming_duties(session: Session, *, subtree_ids: list[uuid.UUID], days: int | None = None) -> list[dict]:
    """List all currently-scheduled duties from today onward, grouped by day.

    ``days`` caps the horizon when given; ``None`` returns everything
    currently scheduled (however far out the algorithm has assigned).
    """
    today = date.today()
    end = today + timedelta(days=days) if days is not None else None

    conditions = [
        DutyAssignment.status.in_(["published", "algorithm_draft"]),
        Soldier.hierarchy_node_id.in_(subtree_ids),
        Soldier.left_at.is_(None),
        DutyAssignment.end_date >= today,
    ]
    if end is not None:
        conditions.append(DutyAssignment.start_date <= end)

    assignments = session.execute(
        select(
            DutyAssignment,
            Soldier.full_name,
            DutyType.name,
            DutyLocation.name,
            HierarchyNode.name,
        )
        .join(Soldier, Soldier.id == DutyAssignment.soldier_id)
        .outerjoin(DutyType, DutyType.id == DutyAssignment.duty_type_id)
        .outerjoin(DutyLocation, DutyLocation.id == DutyAssignment.duty_location_id)
        .outerjoin(HierarchyNode, HierarchyNode.id == Soldier.hierarchy_node_id)
        .where(*conditions)
    ).all()

    # Only days that actually have an assignment get an entry — with no
    # horizon cap, pre-filling every empty day between today and the
    # furthest assignment would be unbounded and pointless.
    day_map: dict[date, list[dict]] = {}

    for a, soldier_name, duty_type_name, location_name, node_name in assignments:
        d = max(a.start_date, today)
        day_limit = min(a.end_date, end + timedelta(days=1)) if end is not None else a.end_date
        while d < day_limit:
            day_map.setdefault(d, []).append(
                {
                    "assignment_id": str(a.id),
                    "soldier_id": str(a.soldier_id),
                    "soldier_name": soldier_name,
                    "duty_type_id": str(a.duty_type_id),
                    "duty_type_name": duty_type_name or "",
                    "duty_location_id": str(a.duty_location_id),
                    "duty_location_name": location_name or "",
                    "start_date": str(a.start_date),
                    "end_date": str(a.end_date),
                    "start_time": a.start_time,
                    "end_time": a.end_time,
                    "shift_id": str(a.duty_shift_id) if a.duty_shift_id else None,
                    "node_name": node_name or "",
                    "is_reserve": a.is_reserve,
                    "status": a.status,
                }
            )
            d += timedelta(days=1)

    result = []
    for dt, assigns in sorted(day_map.items()):
        result.append({"date": str(dt), "assignments": assigns})
    return result


def alerts(session: Session, *, subtree_ids: list[uuid.UUID]) -> list[dict]:
    # Column rows, not ORM entities: building ~20k Soldier entities for an
    # organization-wide scope cost ~0.4 s of the request on its own.
    in_subtree = (Soldier.hierarchy_node_id.in_(subtree_ids), Soldier.left_at.is_(None))
    soldiers = session.execute(
        select(Soldier.id, Soldier.full_name, Soldier.enrolled_at).where(*in_subtree)
    ).all()
    # The same soldiers as a subquery: the follow-up reads filter with it instead
    # of binding all (up to ~20k) ids as array parameters, ~50-90 ms each.
    soldier_id_scope = select(Soldier.id).where(*in_subtree)
    today = date.today()
    next_week = today + timedelta(days=7)

    warning_scores = commander_alert_warning_scores(
        session, soldiers=soldiers, as_of=today, soldier_id_scope=soldier_id_scope
    )

    soldier_ids = {s.id for s in soldiers}
    name_by_id = {s.id: s.full_name for s in soldiers}
    expiring = _soon_expiring_exemptions(
        session, soldier_ids, start=today, end=next_week, soldier_id_scope=soldier_id_scope
    )

    alerts_list: list[dict] = []

    for s in soldiers:
        norm = warning_scores.get(s.id)
        if norm is not None:
            alerts_list.append(
                {
                    "severity": "warning",
                    "soldier_id": s.id,
                    "soldier_name": s.full_name,
                    "message": f"ניקוד מנורמל נמוך: {norm:.2f}",
                }
            )

    for soldier_id, end_date, exemption_type_name in expiring:
        alerts_list.append(
            {
                "severity": "info",
                "soldier_id": soldier_id,
                "soldier_name": name_by_id.get(soldier_id, ""),
                "message": f"תוקף {exemption_type_name} מסתיים ב-{end_date.strftime('%d.%m.%Y')}",
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
                uuid_any("soldier_field_updates.soldier_id", soldier_ids),
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
                uuid_any("exemption_requests.soldier_id", soldier_ids),
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
