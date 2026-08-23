from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.reserve import _hierarchy_distance
from app.audit.writer import write_audit
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink, NotificationType
from app.services.algorithm_bridge import build_hierarchy_maps
from app.services.notifications import create_notification
from app.services.settings_loader import SettingNotFound, get_setting


class ReserveError(Exception):
    """Raised on invalid reserve operations."""


def call_up_reserve(
    session: Session,
    *,
    assignment: DutyAssignment,
    from_date: date,
    to_date: date,
    actor_id: uuid.UUID | None = None,
) -> DutyAssignment:
    """Record הקפצה on a reserve assignment. Replaces any prior call-up range."""
    if not assignment.is_reserve:
        raise ReserveError("not_a_reserve")
    if from_date < assignment.start_date or to_date >= assignment.end_date:
        raise ReserveError("date_out_of_range")
    if to_date < from_date:
        raise ReserveError("bad_date_range")
    before = {
        "called_up_from": assignment.called_up_from.isoformat()
        if assignment.called_up_from
        else None,
        "called_up_to": assignment.called_up_to.isoformat() if assignment.called_up_to else None,
    }
    assignment.called_up_from = from_date
    assignment.called_up_to = to_date
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="reserve.call_up",
        entity_type="duty_assignment",
        entity_id=assignment.id,
        before=before,
        after={"called_up_from": from_date.isoformat(), "called_up_to": to_date.isoformat()},
    )
    create_notification(
        session, soldier_id=assignment.soldier_id,
        type=NotificationType.gimelim_reserve_called_up,
        title="הוקפצת לכיסוי תורנות",
        body=f"הוקפצת לתורנות בתאריכים {from_date} – {to_date}",
        reference_type="duty_assignment", reference_id=assignment.id,
        actor_id=actor_id,
    )
    if assignment.status == "published":
        from app.services.score_projection import refresh_projection_for_assignment_change

        refresh_projection_for_assignment_change(session, assignment=assignment)
    return assignment


def dismiss_primary(
    session: Session,
    *,
    assignment: DutyAssignment,
    from_date: date,
    to_date: date,
    reason: str | None,
    actor_id: uuid.UUID | None = None,
) -> DutyDismissal:
    """Record a dismissal on a primary assignment. Validates no overlap with existing dismissals."""
    if assignment.is_reserve:
        raise ReserveError("not_a_primary")
    if from_date < assignment.start_date or to_date >= assignment.end_date:
        raise ReserveError("date_out_of_range")
    if to_date < from_date:
        raise ReserveError("bad_date_range")
    existing = (
        session.execute(
            select(DutyDismissal).where(DutyDismissal.duty_assignment_id == assignment.id)
        )
        .scalars()
        .all()
    )
    for d in existing:
        if d.dismissed_from <= to_date and d.dismissed_to >= from_date:
            raise ReserveError("overlapping_dismissal")
    dismissal = DutyDismissal(
        duty_assignment_id=assignment.id,
        dismissed_from=from_date,
        dismissed_to=to_date,
        reason=reason,
        created_by=actor_id,
    )
    session.add(dismissal)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="reserve.dismiss",
        entity_type="duty_dismissal",
        entity_id=dismissal.id,
        after={
            "duty_assignment_id": str(assignment.id),
            "dismissed_from": from_date.isoformat(),
            "dismissed_to": to_date.isoformat(),
            "reason": reason,
        },
    )
    create_notification(
        session, soldier_id=assignment.soldier_id,
        type=NotificationType.assignment_removed,
        title="שוחררת מתורנות",
        body=f"שוחררת מתורנות בתאריכים {from_date} – {to_date}" + (f" — {reason}" if reason else ""),
        reference_type="duty_assignment", reference_id=assignment.id,
        actor_id=actor_id,
    )
    if assignment.status == "published":
        from app.services.score_projection import refresh_projection_for_assignment_change

        refresh_projection_for_assignment_change(session, assignment=assignment)
    return dismissal


def get_reserve_candidates(
    session: Session,
    *,
    shift_id: uuid.UUID,
    reserve_assignment_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return other reserves on the shift ranked by min hierarchy distance to the orphaned primaries."""
    link_rows = (
        session.execute(
            select(DutyReserveLink).where(
                DutyReserveLink.reserve_assignment_id == reserve_assignment_id
            )
        )
        .scalars()
        .all()
    )
    if not link_rows:
        return []

    orphan_primary_ids = [lk.primary_assignment_id for lk in link_rows]
    primaries = (
        session.execute(
            select(DutyAssignment).where(DutyAssignment.id.in_(orphan_primary_ids))
        )
        .scalars()
        .all()
    )

    all_reserves = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.duty_shift_id == shift_id,
                DutyAssignment.is_reserve.is_(True),
                DutyAssignment.id != reserve_assignment_id,
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        )
        .scalars()
        .all()
    )
    if not all_reserves:
        return []

    hier_parent, _, soldier_node, _ = build_hierarchy_maps(session)
    primary_nodes = [soldier_node.get(p.soldier_id) for p in primaries]

    results = []
    for r in all_reserves:
        r_node = soldier_node.get(r.soldier_id)
        distances = [
            _hierarchy_distance(p_node, r_node, hier_parent)
            for p_node in primary_nodes
            if p_node is not None and r_node is not None
        ]
        distance = min(distances) if distances else 99
        results.append(
            {
                "assignment_id": r.id,
                "soldier_id": r.soldier_id,
                "distance": distance,
                "called_up_from": r.called_up_from,
                "called_up_to": r.called_up_to,
            }
        )

    results.sort(key=lambda x: x["distance"])
    return results


def dismiss_reserve(
    session: Session,
    *,
    assignment: DutyAssignment,
    from_date: date,
    to_date: date,
    reason: str | None,
    actor_id: uuid.UUID | None = None,
    covering_reserve_id: uuid.UUID | None = None,
) -> tuple[DutyDismissal, list[dict]]:
    """Record a dismissal on a reserve assignment and relink its covered primaries.

    Returns (dismissal, reallocations).
    """
    if not assignment.is_reserve:
        raise ReserveError("not_a_reserve")
    if from_date < assignment.start_date or to_date >= assignment.end_date:
        raise ReserveError("date_out_of_range")
    if to_date < from_date:
        raise ReserveError("bad_date_range")
    existing = (
        session.execute(
            select(DutyDismissal).where(DutyDismissal.duty_assignment_id == assignment.id)
        )
        .scalars()
        .all()
    )
    for d in existing:
        if d.dismissed_from <= to_date and d.dismissed_to >= from_date:
            raise ReserveError("overlapping_dismissal")
    dismissal = DutyDismissal(
        duty_assignment_id=assignment.id,
        dismissed_from=from_date,
        dismissed_to=to_date,
        reason=reason,
        created_by=actor_id,
    )
    session.add(dismissal)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="reserve.dismiss_reserve",
        entity_type="duty_dismissal",
        entity_id=dismissal.id,
        after={
            "duty_assignment_id": str(assignment.id),
            "dismissed_from": from_date.isoformat(),
            "dismissed_to": to_date.isoformat(),
            "reason": reason,
        },
    )
    create_notification(
        session, soldier_id=assignment.soldier_id,
        type=NotificationType.assignment_removed,
        title="שוחררת מכוננות רזרבה",
        body=f"שוחררת מכוננות בתאריכים {from_date} – {to_date}" + (f" — {reason}" if reason else ""),
        reference_type="duty_assignment", reference_id=assignment.id,
        actor_id=actor_id,
    )
    if assignment.status == "published":
        from app.services.score_projection import refresh_projection_for_assignment_change

        refresh_projection_for_assignment_change(session, assignment=assignment)
    if covering_reserve_id is not None:
        link_rows = (
            session.execute(
                select(DutyReserveLink).where(
                    DutyReserveLink.reserve_assignment_id == assignment.id
                )
            )
            .scalars()
            .all()
        )
        reallocations = []
        for lk in link_rows:
            primary_a = session.get(DutyAssignment, lk.primary_assignment_id)
            if primary_a is None:
                continue
            new_link = relink_reserve(
                session,
                primary_assignment=primary_a,
                reserve_assignment_id=covering_reserve_id,
                actor_id=actor_id,
            )
            reallocations.append(
                {
                    "primary_assignment_id": primary_a.id,
                    "old_reserve_assignment_id": assignment.id,
                    "new_reserve_assignment_id": covering_reserve_id,
                    "hierarchy_distance": new_link.hierarchy_distance,
                }
            )
    else:
        reallocations = reallocate_orphaned_primaries(
            session,
            shift_id=assignment.duty_shift_id,
            called_up_reserve_id=assignment.id,
            called_up_from=from_date,
            called_up_to=to_date,
            actor_id=actor_id,
        )
    return dismissal, reallocations


def delete_dismissal(
    session: Session,
    *,
    dismissal: DutyDismissal,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Remove a dismissal record. Audited."""
    write_audit(
        session,
        actor_id=actor_id,
        action="reserve.dismiss_delete",
        entity_type="duty_dismissal",
        entity_id=dismissal.id,
        before={
            "dismissed_from": dismissal.dismissed_from.isoformat(),
            "dismissed_to": dismissal.dismissed_to.isoformat(),
        },
    )
    assignment = session.get(DutyAssignment, dismissal.duty_assignment_id)
    session.delete(dismissal)
    session.flush()
    if assignment is not None and assignment.status == "published":
        from app.services.score_projection import refresh_projection_for_assignment_change

        refresh_projection_for_assignment_change(session, assignment=assignment)


def get_shift_reserve_detail(session: Session, *, shift_id: uuid.UUID) -> dict[str, Any]:
    """Return all primary and reserve assignments for a shift with call-up, dismissal, and link data."""
    assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.duty_shift_id == shift_id,
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        )
        .scalars()
        .all()
    )

    primary_ids = {a.id for a in assignments if not a.is_reserve}

    links = []
    if primary_ids:
        links = (
            session.execute(
                select(DutyReserveLink).where(
                    DutyReserveLink.primary_assignment_id.in_(primary_ids)
                )
            )
            .scalars()
            .all()
        )
    primary_to_reserve = {lk.primary_assignment_id: lk for lk in links}
    reserve_to_primaries: dict[uuid.UUID, list[uuid.UUID]] = {}
    for lk in links:
        reserve_to_primaries.setdefault(lk.reserve_assignment_id, []).append(
            lk.primary_assignment_id
        )

    dismissals_by_assignment: dict[uuid.UUID, list[DutyDismissal]] = {}
    if primary_ids:
        for d in (
            session.execute(
                select(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(primary_ids))
            )
            .scalars()
            .all()
        ):
            dismissals_by_assignment.setdefault(d.duty_assignment_id, []).append(d)

    primaries = []
    for a in assignments:
        if a.is_reserve:
            continue
        link = primary_to_reserve.get(a.id)
        primaries.append(
            {
                "assignment_id": a.id,
                "soldier_id": a.soldier_id,
                "start_date": a.start_date,
                "end_date": a.end_date,
                "status": a.status,
                "dismissals": [
                    {"id": d.id, "from": d.dismissed_from, "to": d.dismissed_to, "reason": d.reason}
                    for d in dismissals_by_assignment.get(a.id, [])
                ],
                "reserve_assignment_id": link.reserve_assignment_id if link else None,
                "reserve_hierarchy_distance": link.hierarchy_distance if link else None,
            }
        )

    reserves = []
    for a in assignments:
        if not a.is_reserve:
            continue
        reserves.append(
            {
                "assignment_id": a.id,
                "soldier_id": a.soldier_id,
                "start_date": a.start_date,
                "end_date": a.end_date,
                "status": a.status,
                "called_up_from": a.called_up_from,
                "called_up_to": a.called_up_to,
                "primary_assignment_ids": reserve_to_primaries.get(a.id, []),
            }
        )

    return {"primaries": primaries, "reserves": reserves}


def relink_reserve(
    session: Session,
    *,
    primary_assignment: DutyAssignment,
    reserve_assignment_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> DutyReserveLink:
    if primary_assignment.is_reserve:
        raise ReserveError("not_a_primary")
    reserve_a = session.get(DutyAssignment, reserve_assignment_id)
    if reserve_a is None:
        raise ReserveError("reserve_not_found")
    if not reserve_a.is_reserve:
        raise ReserveError("not_a_reserve")

    existing = session.execute(
        select(DutyReserveLink).where(
            DutyReserveLink.primary_assignment_id == primary_assignment.id
        )
    ).scalar_one_or_none()
    if existing:
        session.delete(existing)
        session.flush()

    hier_parent, _, soldier_node, _ = build_hierarchy_maps(session)
    p_node = soldier_node.get(primary_assignment.soldier_id)
    r_node = soldier_node.get(reserve_a.soldier_id)
    distance = _hierarchy_distance(p_node, r_node, hier_parent) if p_node and r_node else 99

    link = DutyReserveLink(
        primary_assignment_id=primary_assignment.id,
        reserve_assignment_id=reserve_assignment_id,
        hierarchy_distance=distance,
    )
    session.add(link)
    session.flush()

    write_audit(
        session,
        actor_id=actor_id,
        action="reserve.relink",
        entity_type="duty_reserve_link",
        entity_id=link.id,
        after={
            "primary_assignment_id": str(primary_assignment.id),
            "reserve_assignment_id": str(reserve_assignment_id),
            "hierarchy_distance": distance,
        },
    )
    return link


def reallocate_orphaned_primaries(
    session: Session,
    *,
    shift_id: uuid.UUID,
    called_up_reserve_id: uuid.UUID,
    called_up_from: date,
    called_up_to: date,
    actor_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """After calling up a reserve, find all OTHER primaries linked to that reserve
    and relink them to the closest available reserve on the same shift.

    Returns list of reallocation dicts with old/new reserve info.
    """
    link_rows = (
        session.execute(
            select(DutyReserveLink).where(
                DutyReserveLink.reserve_assignment_id == called_up_reserve_id,
            )
        )
        .scalars()
        .all()
    )

    if not link_rows:
        return []

    orphan_primary_ids = [lk.primary_assignment_id for lk in link_rows]
    primaries = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.id.in_(orphan_primary_ids),
                DutyAssignment.duty_shift_id == shift_id,
            )
        )
        .scalars()
        .all()
    )

    # Filter to primaries overlapping the call-up range
    affected = [
        p for p in primaries if p.start_date <= called_up_to and p.end_date > called_up_from
    ]
    if not affected:
        return []

    # Find available reserves on this shift (not the called-up one, not called-up during overlap)
    all_reserves = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.duty_shift_id == shift_id,
                DutyAssignment.is_reserve.is_(True),
                DutyAssignment.id != called_up_reserve_id,
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        )
        .scalars()
        .all()
    )

    def _is_available(ra: DutyAssignment) -> bool:
        if ra.called_up_from is None or ra.called_up_to is None:
            return True
        return not (ra.called_up_from <= called_up_to and ra.called_up_to >= called_up_from)

    available_reserves = [r for r in all_reserves if _is_available(r)]

    hier_parent, _, soldier_node, _ = build_hierarchy_maps(session)

    results: list[dict[str, Any]] = []
    for p in affected:
        p_node = soldier_node.get(p.soldier_id)
        if p_node is None:
            results.append(
                {
                    "primary_assignment_id": p.id,
                    "old_reserve_assignment_id": called_up_reserve_id,
                    "new_reserve_assignment_id": None,
                    "hierarchy_distance": None,
                    "warning": "no_hierarchy_node",
                }
            )
            continue

        best = None
        best_dist = 999
        for ra in available_reserves:
            r_node = soldier_node.get(ra.soldier_id)
            if r_node is None:
                continue
            dist = _hierarchy_distance(p_node, r_node, hier_parent)
            if dist < best_dist:
                best_dist = dist
                best = ra

        if best is None:
            results.append(
                {
                    "primary_assignment_id": p.id,
                    "old_reserve_assignment_id": called_up_reserve_id,
                    "new_reserve_assignment_id": None,
                    "hierarchy_distance": None,
                    "warning": "no_available_reserve",
                }
            )
            continue

        old_link = session.execute(
            select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == p.id)
        ).scalar_one_or_none()
        if old_link:
            session.delete(old_link)
            session.flush()

        new_link = DutyReserveLink(
            primary_assignment_id=p.id,
            reserve_assignment_id=best.id,
            hierarchy_distance=best_dist,
        )
        session.add(new_link)
        session.flush()

        write_audit(
            session,
            actor_id=actor_id,
            action="reserve.relink",
            entity_type="duty_reserve_link",
            entity_id=new_link.id,
            after={
                "primary_assignment_id": str(p.id),
                "old_reserve_assignment_id": str(called_up_reserve_id),
                "new_reserve_assignment_id": str(best.id),
                "hierarchy_distance": best_dist,
                "reason": "reallocation_after_call_up",
            },
        )

        results.append(
            {
                "primary_assignment_id": p.id,
                "old_reserve_assignment_id": called_up_reserve_id,
                "new_reserve_assignment_id": best.id,
                "hierarchy_distance": best_dist,
            }
        )

    return results


def count_reserve_days_in_window(
    session: Session,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> int:
    """Peak reserve-day count in any W-day window that overlaps [start_date, end_date].

    Includes the candidate range itself alongside existing published/draft reserves.
    Uses the same sliding-window logic as _passes_density in gimelim.py.
    """
    try:
        W = int(get_setting(session, "reserves.window_days"))
    except SettingNotFound:
        W = 30

    rows = session.execute(
        select(DutyAssignment.start_date, DutyAssignment.end_date).where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.is_reserve.is_(True),
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).all()

    # Build the full set of dates: existing reserves + candidate
    all_dates: set[date] = set()
    for row in rows:
        d = row.start_date
        while d < row.end_date:
            all_dates.add(d)
            d += timedelta(days=1)
    d = start_date
    while d < end_date:
        all_dates.add(d)
        d += timedelta(days=1)

    if not all_dates:
        return 0

    sorted_dates = sorted(all_dates)
    peak = 0
    for anchor in sorted_dates:
        window_end = anchor + timedelta(days=W - 1)
        count = sum(1 for x in sorted_dates if anchor <= x <= window_end)
        if count > peak:
            peak = count
    return peak


def check_reserve_cap(
    session: Session,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> tuple[bool, int, int]:
    """Return (passes, current_peak_days, max_allowed).

    passes=True means adding [start_date, end_date] stays within the cap.
    """
    try:
        max_days = int(get_setting(session, "reserves.max_days_per_window"))
    except SettingNotFound:
        max_days = 14

    peak = count_reserve_days_in_window(session, soldier_id, start_date, end_date)
    return peak <= max_days, peak, max_days


def get_current_reserve_stats(
    session: Session,
    soldier_id: uuid.UUID,
) -> dict:
    """Return { used_days, max_days, window_days } for the rolling window ending today."""
    try:
        W = int(get_setting(session, "reserves.window_days"))
    except SettingNotFound:
        W = 30
    try:
        max_days = int(get_setting(session, "reserves.max_days_per_window"))
    except SettingNotFound:
        max_days = 14

    today = date.today()
    window_start = today - timedelta(days=W - 1)

    rows = session.execute(
        select(DutyAssignment.start_date, DutyAssignment.end_date).where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.is_reserve.is_(True),
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
            DutyAssignment.end_date >= window_start,
            DutyAssignment.start_date <= today,
        )
    ).all()

    all_dates: set[date] = set()
    for row in rows:
        d = row.start_date
        while d < row.end_date:
            all_dates.add(d)
            d += timedelta(days=1)

    used = sum(1 for d in all_dates if window_start <= d <= today)
    return {"used_days": used, "max_days": max_days, "window_days": W}
