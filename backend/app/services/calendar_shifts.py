from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.duration import combine_date_time
from app.db.models import (
    DutyAssignment,
    DutyDismissal,
    DutyReserveLink,
    DutyShift,
    DutyType,
    DutyLocation,
    ExemptionDutyTypeMap,
    ForcedCallup,
    HierarchyNode,
    SoldierExemption,
    Soldier,
    SystemSetting,
)
from app.services.range_eligibility_projection import (
    count_ineligible_soldiers_for_duties,
    project_duty_eligibility,
)


def _duty_color_for(duty_type_id: uuid.UUID) -> str:
    """Deterministic color from a duty_type_id alone — used when the id
    isn't present in the loaded DutyType map (e.g. a dangling reference),
    so a shift never falls back to an invalid empty color (which renders
    as black in the calendar UI)."""
    hue = hash(duty_type_id) % 360
    # Hues in the yellow band read as washed-out against the calendar's
    # white event text (worse once the hover brightness filter brightens
    # both background and text toward white together) — darken just that
    # band to keep it legible.
    lightness = 42 if 40 <= hue <= 70 else 55
    return f"hsl({hue}, 65%, {lightness}%)"


def _shift_instants(shift: DutyShift) -> tuple[Any, Any]:
    """Wall-clock start/end of a shift, for hour-aware calendar views.

    `shift.end_date` is exclusive (the first day NOT touched), so the shift's
    actual last calendar day is `end_date - 1 day`, which is where `end_time`
    applies.
    """
    last_day = shift.end_date - timedelta(days=1)
    return combine_date_time(shift.start_date, shift.start_time), combine_date_time(last_day, shift.end_time)


def _attach_range_eligibility_facts(session: Session, shifts: list[dict[str, Any]]) -> None:
    """Attach shared duty-date eligibility facts to calendar assignees in place."""
    duty_pairs = {
        (assignee["soldier_id"], assignee["assignment_id"])
        for shift in shifts
        for assignee in shift["assignees"]
    }
    if not duty_pairs:
        return
    facts = project_duty_eligibility(
        session,
        soldier_ids=[soldier_id for soldier_id, _assignment_id in duty_pairs],
        duty_ids=[assignment_id for _soldier_id, assignment_id in duty_pairs],
        as_of=date.today(),
    )
    for shift in shifts:
        for assignee in shift["assignees"]:
            fact = facts.get((assignee["soldier_id"], assignee["assignment_id"]))
            assignee["range_eligibility"] = (
                {
                    "eligible": fact.eligible,
                    "required_range_type": fact.required_range_type,
                    "qualification_source": fact.qualification_source,
                    "covered_by_range_date": fact.covered_by_range_date,
                    "covering_range_type": fact.covering_range_type,
                    "projected_valid_until": fact.projected_valid_until,
                    "reason": fact.reason,
                    "duty_type_name": shift["duty_type_name"],
                    "start_date": shift["start_date"],
                    "last_qualification_type": fact.last_qualification_type,
                    "last_qualification_date": fact.last_qualification_date,
                }
                if fact is not None
                else None
            )


def _attach_duty_problems(session: Session, shifts: list[dict[str, Any]]) -> None:
    """Attach non-sensitive operational conflicts to each displayed assignment."""
    entries = [
        (shift, assignee)
        for shift in shifts
        for assignee in shift["assignees"]
    ]
    if not entries:
        return

    assignment_ids = {assignee["assignment_id"] for _shift, assignee in entries}
    by_assignment = {assignee["assignment_id"]: (shift, assignee) for shift, assignee in entries}
    for _shift, assignee in entries:
        assignee["problems"] = []

    for dismissal in session.execute(
        select(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(assignment_ids))
    ).scalars():
        target = by_assignment.get(dismissal.duty_assignment_id)
        if target is None:
            continue
        _shift, assignee = target
        kind = "gimelim" if dismissal.is_gimelim else "inability_to_attend"
        assignee["problems"].append({
            "kind": kind,
            "source_id": dismissal.id,
            "from_date": dismissal.dismissed_from,
            "to_date": dismissal.dismissed_to,
            "reason": dismissal.reason,
        })

    soldier_ids = {assignee["soldier_id"] for _shift, assignee in entries}
    exemptions = session.execute(
        select(SoldierExemption).where(
            SoldierExemption.soldier_id.in_(soldier_ids),
            SoldierExemption.revoked_at.is_(None),
        )
    ).scalars().all()
    mapped_duty_types = {
        (row.exemption_type_id, row.duty_type_id)
        for row in session.execute(select(ExemptionDutyTypeMap)).scalars()
    }
    for exemption in exemptions:
        for shift, assignee in entries:
            if assignee["soldier_id"] != exemption.soldier_id:
                continue
            if (exemption.exemption_type_id, shift["duty_type_id"]) not in mapped_duty_types:
                continue
            last_day = shift["end_date"] - timedelta(days=1)
            if exemption.start_date > last_day or (exemption.end_date and exemption.end_date < shift["start_date"]):
                continue
            assignee["problems"].append({
                "kind": "duty_exemption",
                "source_id": exemption.id,
                "from_date": max(exemption.start_date, shift["start_date"]),
                "to_date": min(exemption.end_date or last_day, last_day),
                "reason": None,
            })

    for callup in session.execute(
        select(ForcedCallup).where(
            ForcedCallup.original_assignment_id.in_(assignment_ids),
            ForcedCallup.status == "approved",
        )
    ).scalars():
        target = by_assignment.get(callup.original_assignment_id)
        if target is None:
            continue
        shift, assignee = target
        assignee["problems"].append({
            "kind": "hakpaza_pikudit",
            "source_id": callup.id,
            "from_date": callup.pull_date,
            "to_date": shift["end_date"] - timedelta(days=1),
            "reason": None,
        })


def get_calendar_shifts(
    session: Session,
    *,
    node_id: uuid.UUID | None = None,
    soldier_id: uuid.UUID | None = None,
    date_from: date | None,
    date_to: date | None,
    include_eligibility_facts: bool = False,
) -> list[dict[str, Any]]:
    if soldier_id is not None:
        # Personal view: only this soldier's own assignments, regardless of
        # which node they (or their duties) belong to.
        soldier = session.get(Soldier, soldier_id)
        if soldier is None:
            return []
        soldiers_in_subtree = {
            soldier.id: (soldier.full_name, soldier.hierarchy_node_id, soldier.profile_picture_url)
        }
    else:
        node = session.get(HierarchyNode, node_id)
        if node is None:
            return []
        root_setting = session.get(SystemSetting, "system.root_node_id")
        is_framework_wide = root_setting is not None and str(node_id) == str(root_setting.value)

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
        if not soldiers_in_subtree and not is_framework_wide:
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

    dt_map: dict[uuid.UUID, tuple[str, str, str | None]] = {}
    for dt in session.execute(select(DutyType)).scalars().all():
        dt_map[dt.id] = (dt.name, _duty_color_for(dt.id), dt.required_range_type)

    loc_map = {dl.id: dl.name for dl in session.execute(select(DutyLocation)).scalars().all()}

    # All active shifts in the date range (includes template-generated shifts with no assignments)
    shift_query = select(DutyShift).where(DutyShift.status == "active")
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
            "weapon_ineligible": a.weapon_ineligible,
            "weapon_ineligible_reason": a.weapon_ineligible_reason,
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
        extra_soldiers: dict[uuid.UUID, tuple[str, str | None, uuid.UUID | None]] = {}
        if extra_soldier_ids:
            for s in (
                session.execute(select(Soldier).where(Soldier.id.in_(extra_soldier_ids)))
                .scalars()
                .all()
            ):
                extra_soldiers[s.id] = (s.full_name, s.profile_picture_url, s.hierarchy_node_id)
        for a in extra_assigns:
            subtree_data = soldiers_in_subtree.get(a.soldier_id)
            if subtree_data:
                name = subtree_data[0]
                sol_node = subtree_data[1]
                pic = subtree_data[2] if len(subtree_data) > 2 else None
            else:
                extra_data = extra_soldiers.get(a.soldier_id, ("", None, None))
                name = extra_data[0]
                pic = extra_data[1]
                sol_node = extra_data[2]
            assignees_by_shift.setdefault(a.duty_shift_id, []).append({
                "assignment_id": a.id,
                "soldier_id": a.soldier_id,
                "soldier_name": name,
                "hierarchy_label": _leaf_label(sol_node),
                "hierarchy_path_ids": _leaf_path_ids(sol_node),
                "is_reserve": True,
                "profile_picture_url": pic,
                "called_up_from": a.called_up_from,
                "called_up_to": a.called_up_to,
                "primary_assignment_ids": reserve_to_primaries.get(a.id, []),
                "weapon_ineligible": a.weapon_ineligible,
                "weapon_ineligible_reason": a.weapon_ineligible_reason,
            })

    result = []
    for shift in shifts:
        assignees = assignees_by_shift.get(shift.id, [])
        # The base query above pulls every active shift in range, unfiltered.
        if soldier_id is not None:
            # Personal view: skip shifts this soldier isn't actually assigned to.
            if not assignees:
                continue
        elif not assignees and not is_framework_wide:
            # A hierarchy-scoped view only shows duties with an assignee in the
            # selected subtree. Open duties have no unit membership to match.
            continue
        dt_name, dt_color, required_range_type = dt_map.get(
            shift.duty_type_id, ("", _duty_color_for(shift.duty_type_id), None)
        )
        primary_count = sum(1 for a_ in assignees if not a_["is_reserve"])
        reserve_count = sum(
            1 for a_ in assignees if a_["is_reserve"] and not a_.get("called_up_from")
        )
        start_at, end_at = _shift_instants(shift)
        result.append(
            {
                "id": shift.id,
                "duty_type_id": shift.duty_type_id,
                "duty_type_name": dt_name,
                "duty_type_color": dt_color,
                "required_range_type": required_range_type,
                "duty_location_name": loc_map.get(shift.duty_location_id, ""),
                "start_date": shift.start_date,
                "end_date": shift.end_date,
                "start_time": shift.start_time,
                "end_time": shift.end_time,
                "start_at": start_at,
                "end_at": end_at,
                "required_count": shift.required_count,
                "assigned_count": primary_count,
                "fill_status": "full"
                if primary_count >= shift.required_count
                else ("partial" if primary_count > 0 else "empty"),
                "reserve_count": reserve_count,
                "assignees": assignees,
            }
        )

    _attach_duty_problems(session, result)
    if include_eligibility_facts:
        _attach_range_eligibility_facts(session, result)
    return result


def count_calendar_weapon_ineligible_soldiers(
    session: Session,
    *,
    node_id: uuid.UUID | None = None,
    soldier_id: uuid.UUID | None = None,
    date_from: date | None,
    date_to: date | None,
    visible_soldier_ids: set[uuid.UUID] | None = None,
) -> int:
    """Count distinct active assignees who are ineligible in the visible calendar.

    The calendar rows establish the caller-selected subtree/personal scope and
    date range. Counts start today even when the visible window includes the
    past. The shared projection then evaluates each displayed duty on its own
    scheduled date, including only confirmed main-range coverage.
    """
    shifts = get_calendar_shifts(
        session,
        node_id=node_id,
        soldier_id=soldier_id,
        date_from=max(date_from, date.today()) if date_from else date.today(),
        date_to=date_to,
    )
    duty_pairs = {
        (assignee["soldier_id"], assignee["assignment_id"])
        for shift in shifts
        for assignee in shift["assignees"]
        if (not assignee["is_reserve"] or assignee["called_up_from"])
        and (visible_soldier_ids is None or assignee["soldier_id"] in visible_soldier_ids)
    }
    if not duty_pairs:
        return 0
    return count_ineligible_soldiers_for_duties(
        session,
        soldier_ids=[soldier_id for soldier_id, _ in duty_pairs],
        duty_ids=[assignment_id for _, assignment_id in duty_pairs],
        as_of=date.today(),
    )


def get_single_shift(session: Session, *, shift_id: uuid.UUID) -> dict[str, Any] | None:
    """Return a CalendarShift-shaped dict for a single shift (no node-scope filter)."""
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        return None

    dt_map: dict[uuid.UUID, tuple[str, str, str | None]] = {}
    for dt in session.execute(select(DutyType)).scalars().all():
        dt_map[dt.id] = (dt.name, _duty_color_for(dt.id), dt.required_range_type)

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

    dt_name, dt_color, required_range_type = dt_map.get(
        shift.duty_type_id, ("", _duty_color_for(shift.duty_type_id), None)
    )
    start_at, end_at = _shift_instants(shift)
    base = {
        "id": shift.id,
        "duty_type_id": shift.duty_type_id,
        "duty_type_name": dt_name,
        "duty_type_color": dt_color,
        "required_range_type": required_range_type,
        "duty_location_name": loc_map.get(shift.duty_location_id, ""),
        "start_date": shift.start_date,
        "end_date": shift.end_date,
        "start_time": shift.start_time,
        "end_time": shift.end_time,
        "start_at": start_at,
        "end_at": end_at,
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
            "weapon_ineligible": a.weapon_ineligible,
            "weapon_ineligible_reason": a.weapon_ineligible_reason,
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

    result = {
        **base,
        "assigned_count": primary_count,
        "fill_status": fill,
        "reserve_count": reserve_count,
        "assignees": assignees,
    }
    _attach_duty_problems(session, [result])
    _attach_range_eligibility_facts(session, [result])
    return result
