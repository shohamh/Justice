from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.reserve import _hierarchy_distance
from app.audit.writer import write_audit
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink
from app.services.algorithm_bridge import build_hierarchy_maps


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
    if from_date < assignment.start_date or to_date > assignment.end_date:
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
    if from_date < assignment.start_date or to_date > assignment.end_date:
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
    return dismissal


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
    session.delete(dismissal)


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
