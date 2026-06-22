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
        s.id: (s.full_name, s.hierarchy_node_id, s.profile_picture_url)
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

    def _leaf_label(hierarchy_node_id: uuid.UUID | None) -> str | None:
        if hierarchy_node_id is None:
            return None
        leaf = all_nodes.get(hierarchy_node_id)
        if leaf is None:
            return None
        parent = all_nodes.get(leaf.parent_id) if leaf.parent_id else None
        return f"{parent.name} / {leaf.name}" if parent else leaf.name

    def _leaf_path_ids(hierarchy_node_id: uuid.UUID | None) -> list[str]:
        if hierarchy_node_id is None:
            return []
        leaf = all_nodes.get(hierarchy_node_id)
        if leaf is None:
            return []
        return [str(pid) for pid in (leaf.path_ids or [])]

    dt_map: dict[uuid.UUID, tuple[str, str]] = {}
    for dt in session.execute(select(DutyType)).scalars().all():
        h = hash(dt.id) % 360
        dt_map[dt.id] = (dt.name, f"hsl({h}, 65%, 55%)")

    loc_map = {dl.id: dl.name for dl in session.execute(select(DutyLocation)).scalars().all()}

    subtree_shift_ids = (
        session.execute(
            select(DutyAssignment.duty_shift_id)
            .where(DutyAssignment.soldier_id.in_(soldier_id_set))
            .distinct()
        )
        .scalars()
        .all()
    )
    if not subtree_shift_ids:
        return []

    shift_query = select(DutyShift).where(DutyShift.id.in_(subtree_shift_ids))
    if date_from:
        shift_query = shift_query.where(DutyShift.end_date > date_from)
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
    reserve_ids = [a.id for a in assignments if a.is_reserve]

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

    dismissals_by_reserve: dict[uuid.UUID, list[DutyDismissal]] = {}
    if reserve_ids:
        for d in (
            session.execute(
                select(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(reserve_ids))
            )
            .scalars()
            .all()
        ):
            dismissals_by_reserve.setdefault(d.duty_assignment_id, []).append(d)

    assignees_by_shift: dict[uuid.UUID, list[dict]] = {}
    for a in assignments:
        assignees_by_shift.setdefault(a.duty_shift_id, [])
        sol_data = soldiers_in_subtree.get(a.soldier_id, ("", None, None))
        sol_name, sol_node, sol_pic = sol_data[0], sol_data[1], sol_data[2] if len(sol_data) > 2 else None
        entry: dict = {
            "assignment_id": a.id,
            "soldier_id": a.soldier_id,
            "soldier_name": sol_name,
            "hierarchy_label": _leaf_label(sol_node),
            "hierarchy_path_ids": _leaf_path_ids(sol_node),
            "is_reserve": a.is_reserve,
            "profile_picture_url": sol_pic,
        }
        if a.is_reserve:
            entry["called_up_from"] = a.called_up_from
            entry["called_up_to"] = a.called_up_to
            entry["primary_assignment_ids"] = reserve_to_primaries.get(a.id, [])
            entry["dismissals"] = [
                {
                    "id": d.id,
                    "dismissed_from": d.dismissed_from,
                    "dismissed_to": d.dismissed_to,
                    "reason": d.reason,
                }
                for d in dismissals_by_reserve.get(a.id, [])
            ]
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

    # Include reserve assignments whose soldiers are outside the queried subtree.
    # Without this, their assignment_id appears in a primary's reserve_assignment_id
    # but is missing from assignees, causing the frontend to show a raw UUID.
    linked_reserve_ids = {lk.reserve_assignment_id for lk in links}
    already_loaded_ids = {a.id for a in assignments}
    missing_reserve_ids = linked_reserve_ids - already_loaded_ids
    if missing_reserve_ids:
        extra_assigns = (
            session.execute(
                select(DutyAssignment).where(DutyAssignment.id.in_(missing_reserve_ids))
            )
            .scalars()
            .all()
        )
        extra_soldier_ids = {a.soldier_id for a in extra_assigns} - set(soldiers_in_subtree)
        extra_soldiers: dict[uuid.UUID, tuple[str, str | None]] = {}
        if extra_soldier_ids:
            for s in (
                session.execute(select(Soldier).where(Soldier.id.in_(extra_soldier_ids)))
                .scalars()
                .all()
            ):
                extra_soldiers[s.id] = (s.full_name, s.profile_picture_url)
        for a in extra_assigns:
            subtree_data = soldiers_in_subtree.get(a.soldier_id)
            if subtree_data:
                name = subtree_data[0]
                pic = subtree_data[2] if len(subtree_data) > 2 else None
            else:
                extra_data = extra_soldiers.get(a.soldier_id, ("", None))
                name = extra_data[0]
                pic = extra_data[1]
            assignees_by_shift.setdefault(a.duty_shift_id, []).append({
                "assignment_id": a.id,
                "soldier_id": a.soldier_id,
                "soldier_name": name,
                "hierarchy_label": None,
                "hierarchy_path_ids": [],
                "is_reserve": True,
                "profile_picture_url": pic,
                "called_up_from": a.called_up_from,
                "called_up_to": a.called_up_to,
                "primary_assignment_ids": reserve_to_primaries.get(a.id, []),
            })

    result = []
    for shift in shifts:
        assignees = assignees_by_shift.get(shift.id, [])
        if not assignees:
            continue
        dt_name, dt_color = dt_map.get(shift.duty_type_id, ("", ""))
        primary_count = sum(1 for a_ in assignees if not a_["is_reserve"])
        reserve_count = sum(
            1 for a_ in assignees if a_["is_reserve"] and not a_.get("called_up_from")
        )
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


def get_single_shift(session: Session, *, shift_id: uuid.UUID) -> dict[str, Any] | None:
    """Return a CalendarShift-shaped dict for a single shift (no node-scope filter)."""
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        return None

    dt_map: dict[uuid.UUID, tuple[str, str]] = {}
    for dt in session.execute(select(DutyType)).scalars().all():
        h = hash(dt.id) % 360
        dt_map[dt.id] = (dt.name, f"hsl({h}, 65%, 55%)")

    loc_map = {dl.id: dl.name for dl in session.execute(select(DutyLocation)).scalars().all()}

    all_nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}

    def _leaf_label(node_id: uuid.UUID | None) -> str | None:
        if node_id is None:
            return None
        leaf = all_nodes.get(node_id)
        if leaf is None:
            return None
        parent = all_nodes.get(leaf.parent_id) if leaf.parent_id else None
        return f"{parent.name} / {leaf.name}" if parent else leaf.name

    def _leaf_path_ids(node_id: uuid.UUID | None) -> list[str]:
        if node_id is None:
            return []
        leaf = all_nodes.get(node_id)
        if leaf is None:
            return []
        return [str(pid) for pid in (leaf.path_ids or [])]

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

    dt_name, dt_color = dt_map.get(shift.duty_type_id, ("", ""))
    base = {
        "id": shift.id,
        "duty_type_id": shift.duty_type_id,
        "duty_type_name": dt_name,
        "duty_type_color": dt_color,
        "duty_location_name": loc_map.get(shift.duty_location_id, ""),
        "start_date": shift.start_date,
        "end_date": shift.end_date,
        "required_count": shift.required_count,
    }

    if not assignments:
        return {**base, "assigned_count": 0, "fill_status": "empty", "reserve_count": 0, "assignees": []}

    primary_ids = [a.id for a in assignments if not a.is_reserve]

    links: list[DutyReserveLink] = []
    if primary_ids:
        links = (
            session.execute(
                select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id.in_(primary_ids))
            )
            .scalars()
            .all()
        )

    primary_to_link = {lk.primary_assignment_id: lk for lk in links}
    reserve_to_primaries: dict[uuid.UUID, list[uuid.UUID]] = {}
    for lk in links:
        reserve_to_primaries.setdefault(lk.reserve_assignment_id, []).append(lk.primary_assignment_id)

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

    soldier_ids = {a.soldier_id for a in assignments}
    soldiers = {
        s.id: s
        for s in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars().all()
    }

    assignees = []
    for a in assignments:
        sol = soldiers.get(a.soldier_id)
        entry: dict = {
            "assignment_id": a.id,
            "soldier_id": a.soldier_id,
            "soldier_name": sol.full_name if sol else "",
            "hierarchy_label": _leaf_label(sol.hierarchy_node_id if sol else None),
            "hierarchy_path_ids": _leaf_path_ids(sol.hierarchy_node_id if sol else None),
            "is_reserve": a.is_reserve,
            "profile_picture_url": sol.profile_picture_url if sol else None,
            "dismissals": [],
            "reserve_assignment_id": None,
            "reserve_hierarchy_distance": None,
            "called_up_from": None,
            "called_up_to": None,
            "primary_assignment_ids": [],
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
        assignees.append(entry)

    primary_count = sum(1 for e in assignees if not e["is_reserve"])
    reserve_count = sum(1 for e in assignees if e["is_reserve"] and not e.get("called_up_from"))
    fill = "full" if primary_count >= shift.required_count else ("partial" if primary_count > 0 else "empty")

    return {**base, "assigned_count": primary_count, "fill_status": fill, "reserve_count": reserve_count, "assignees": assignees}
