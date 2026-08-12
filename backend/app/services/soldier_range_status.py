from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import node_in_scope
from app.db.models import DutyType, HierarchyNode, Soldier
from app.services.weapon_eligibility import (
    _enforce_enabled,
    _future_windows_by_soldier_and_required_type,
    _is_eligible_from_data,
    _latest_qualification_by_soldier,
    _max_qualification_valid_untils,
    _pending_excusal_disqualifies,
)


@dataclass(frozen=True)
class RangeStatus:
    required_range_type: str
    eligible: bool
    qualification_source: str | None
    covered_by_range_date: date | None
    covering_range_type: str | None
    projected_valid_until: date | None
    last_qualification_type: str | None
    last_qualification_date: date | None


def _relevant_required_range_types(session: Session, *, soldier: Soldier) -> set[str]:
    """required_range_type tiers structurally reachable by this soldier's node,
    independent of any specific scheduled duty. Mirrors the structural-eligibility
    pattern in range_exemption.py's _has_any_eligible_weapon_duty_type."""
    if soldier.hierarchy_node_id is None:
        return set()
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        return set()
    duty_types = session.execute(
        select(DutyType).where(
            DutyType.required_range_type.is_not(None), DutyType.active.is_(True),
        )
    ).scalars().all()
    return {
        duty_type.required_range_type
        for duty_type in duty_types
        if node_in_scope(duty_type.eligible_node_ids, node.path_ids)
    }


def list_relevant_range_statuses(session: Session, *, soldier: Soldier) -> list[RangeStatus]:
    """Range-qualification status for a soldier, independent of any specific duty —
    "as of today," one entry per required_range_type tier relevant to their node."""
    required_types = _relevant_required_range_types(session, soldier=soldier)
    if not required_types:
        return []

    as_of = date.today()
    latest_qualifications = _latest_qualification_by_soldier(session, soldier_ids=[soldier.id])
    latest = latest_qualifications.get(soldier.id)

    if not _enforce_enabled(session):
        return [
            RangeStatus(
                required_range_type=required_type,
                eligible=True,
                qualification_source="enforcement_disabled",
                covered_by_range_date=None,
                covering_range_type=None,
                projected_valid_until=None,
                last_qualification_type=latest[0] if latest else None,
                last_qualification_date=latest[1] if latest else None,
            )
            for required_type in sorted(required_types)
        ]

    valid_untils = _max_qualification_valid_untils(
        session, soldier_ids=[soldier.id], required_range_types=list(required_types),
    )
    future_windows = _future_windows_by_soldier_and_required_type(
        session,
        soldier_ids=[soldier.id],
        required_range_types=list(required_types),
        disqualify_pending=_pending_excusal_disqualifies(session),
        future_start=as_of,
    )

    statuses: list[RangeStatus] = []
    for required_type in sorted(required_types):
        current_valid_until = valid_untils[soldier.id, required_type]
        windows = future_windows[soldier.id, required_type]
        eligible = _is_eligible_from_data(
            current_best_valid_until=current_valid_until, future_windows=windows, as_of=as_of,
        )
        matching_window = next(
            (window for window in windows if window[0] <= as_of <= window[1]), None,
        )
        if current_valid_until is not None and current_valid_until >= as_of:
            qualification_source = "current_qualification"
            covered_by_range_date = None
            covering_range_type = None
            projected_valid_until = current_valid_until
        elif matching_window is not None:
            qualification_source = "planned_range"
            covered_by_range_date, projected_valid_until, covering_range_type = matching_window
        else:
            qualification_source = None
            covered_by_range_date = None
            covering_range_type = None
            projected_valid_until = None
        statuses.append(RangeStatus(
            required_range_type=required_type,
            eligible=eligible,
            qualification_source=qualification_source,
            covered_by_range_date=covered_by_range_date,
            covering_range_type=covering_range_type,
            projected_valid_until=projected_valid_until,
            last_qualification_type=latest[0] if latest else None,
            last_qualification_date=latest[1] if latest else None,
        ))
    return statuses
