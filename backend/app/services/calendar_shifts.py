from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyReserveLink,
    DutyShift,
    DutyType,
    DutyLocation,
    HierarchyNode,
    Soldier,
)


def get_calendar_shifts(
    session: Session, *, node_id: uuid.UUID, date_from: date | None, date_to: date | None
) -> list[dict[str, Any]]:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        return []

    subtree_node_ids = set(
        session.execute(select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_id)))
        .scalars()
        .all()
    )

    soldiers_in_subtree = {
        s.id: s.full_name
        for s in session.execute(
            select(Soldier).where(
                Soldier.hierarchy_node_id.in_(subtree_node_ids),
                Soldier.left_at.is_(None),
            )
        )
        .scalars()
        .all()
    }
    if not soldiers_in_subtree:
        return []

    soldier_id_set = set(soldiers_in_subtree.keys())

    all_nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}

    def _leaf_label(sid: uuid.UUID) -> str | None:
        s = session.get(Soldier, sid)
        if s is None or s.hierarchy_node_id is None:
            return None
        leaf = all_nodes.get(s.hierarchy_node_id)
        if leaf is None:
            return None
        parent = all_nodes.get(leaf.parent_id) if leaf.parent_id else None
        return f"{parent.name} / {leaf.name}" if parent else leaf.name

    dt_map: dict[uuid.UUID, tuple[str, str]] = {}
    for dt in session.execute(select(DutyType)).scalars().all():
        h = hash(dt.id) % 360
        dt_map[dt.id] = (dt.name, f"hsl({h}, 65%, 55%)")

    loc_map = {dl.id: dl.name for dl in session.execute(select(DutyLocation)).scalars().all()}

    shift_query = select(DutyShift)
    if date_from:
        shift_query = shift_query.where(DutyShift.end_date >= date_from)
    if date_to:
        shift_query = shift_query.where(DutyShift.start_date <= date_to)
    shifts = session.execute(shift_query).scalars().all()

    if not shifts:
        return []

    shift_ids = [s.id for s in shifts]

    assignments = (
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.duty_shift_id.in_(shift_ids),
                DutyAssignment.soldier_id.in_(soldier_id_set),
                DutyAssignment.status.in_(["published", "algorithm_draft"]),
            )
        )
        .scalars()
        .all()
    )

    if not assignments:
        return []

    assignment_ids = [a.id for a in assignments]
    primary_ids = [a.id for a in assignments if not a.is_reserve]

    links: list[DutyReserveLink] = []
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

    primary_to_link = {lk.primary_assignment_id: lk for lk in links}
    reserve_to_primaries: dict[uuid.UUID, list[uuid.UUID]] = {}
    for lk in links:
        reserve_to_primaries.setdefault(lk.reserve_assignment_id, []).append(
            lk.primary_assignment_id
        )

    dismissals_by_primary: dict[uuid.UUID, list[DutyDismissal]] = {}
    if primary_ids:
        for d in (
            session.execute(
                select(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(primary_ids))
            )
            .scalars()
            .all()
        ):
            dismissals_by_primary.setdefault(d.duty_assignment_id, []).append(d)

    assignees_by_shift: dict[uuid.UUID, list[dict]] = {}
    for a in assignments:
        assignees_by_shift.setdefault(a.duty_shift_id, [])
        entry: dict = {
            "soldier_id": a.soldier_id,
            "soldier_name": soldiers_in_subtree.get(a.soldier_id, ""),
            "hierarchy_label": _leaf_label(a.soldier_id),
            "is_reserve": a.is_reserve,
        }
        if a.is_reserve:
            entry["called_up_from"] = a.called_up_from
            entry["called_up_to"] = a.called_up_to
            entry["primary_assignment_ids"] = reserve_to_primaries.get(a.id, [])
        else:
            link = primary_to_link.get(a.id)
            entry["dismissals"] = [
                {
                    "id": d.id,
                    "dismissed_from": d.dismissed_from,
                    "dismissed_to": d.dismissed_to,
                    "reason": d.reason,
                }
                for d in dismissals_by_primary.get(a.id, [])
            ]
            entry["reserve_assignment_id"] = link.reserve_assignment_id if link else None
            entry["reserve_hierarchy_distance"] = link.hierarchy_distance if link else None

        assignees_by_shift[a.duty_shift_id].append(entry)

    result = []
    for shift in shifts:
        assignees = assignees_by_shift.get(shift.id, [])
        if not assignees:
            continue
        dt_name, dt_color = dt_map.get(shift.duty_type_id, ("", ""))
        primary_count = sum(1 for a_ in assignees if not a_["is_reserve"])
        reserve_count = sum(1 for a_ in assignees if a_["is_reserve"])
        result.append(
            {
                "id": shift.id,
                "duty_type_id": shift.duty_type_id,
                "duty_type_name": dt_name,
                "duty_type_color": dt_color,
                "duty_location_name": loc_map.get(shift.duty_location_id, ""),
                "start_date": shift.start_date,
                "end_date": shift.end_date,
                "required_count": shift.required_count,
                "assigned_count": primary_count,
                "fill_status": "full"
                if primary_count >= shift.required_count
                else ("partial" if primary_count > 0 else "empty"),
                "reserve_count": reserve_count,
                "assignees": assignees,
            }
        )

    return result
