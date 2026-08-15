"""Shared duty/soldier eligibility facts for solving and diagnostics."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, node_in_scope


@dataclass(frozen=True)
class DutyAvailability:
    eligible_count: int
    available_count: int
    blocker_counts: dict[str, int]


def _duty_dates(duty: DutyBlock) -> set[date]:
    dates: set[date] = set()
    current = duty.start_date
    while current < duty.end_date:
        dates.add(current)
        current += timedelta(days=1)
    return dates


def eligibility_blockers(
    soldier: SoldierInput,
    duty: DutyBlock,
    *,
    enforce_weapon_qualification: bool = True,
    duty_dates: set[date] | None = None,
) -> set[str]:
    """Return every hard eligibility reason that blocks this soldier/duty pair."""
    blockers: set[str] = set()

    if duty.duty_type_id in soldier.exempted_duty_type_ids:
        blockers.add("duty_type_exemption")
    if duty.duty_location_id in soldier.exempted_duty_location_ids:
        blockers.add("duty_location_exemption")
    duty_dates = duty_dates if duty_dates is not None else _duty_dates(duty)
    if any(
        start <= duty_date <= end
        for start, end in soldier.approved_constraint_dates
        for duty_date in duty_dates
    ):
        blockers.add("personal_constraint")
    if not node_in_scope(duty.eligible_node_ids, soldier.path_ids):
        blockers.add("hierarchy_scope")

    if enforce_weapon_qualification and duty.id in soldier.weapon_ineligible_duty_block_ids:
        blockers.add("range_qualification" if duty.required_range_type else "weapon_qualification")

    if duty.id in soldier.future_ineligible_duty_block_ids:
        classified = False
        if duty.required_range_type:
            blockers.add("range_qualification")
            classified = True
        if duty.requirements.get("requires_military_driving_license"):
            blockers.add("military_driving_license")
            classified = True
        if not classified:
            blockers.add("duty_requirements")

    return blockers


def is_eligible(
    soldier: SoldierInput,
    duty: DutyBlock,
    *,
    enforce_weapon_qualification: bool = True,
) -> bool:
    return not eligibility_blockers(
        soldier, duty, enforce_weapon_qualification=enforce_weapon_qualification
    )


def analyze_duty_availability(
    soldiers: Sequence[SoldierInput],
    duty: DutyBlock,
    *,
    existing: Sequence[ExistingAssignment] = (),
    enforce_weapon_qualification: bool = True,
) -> DutyAvailability:
    """Summarize hard eligibility and current schedule availability for one duty."""
    blocker_counts: dict[str, int] = {}
    eligible_count = 0
    available_count = 0
    for soldier in soldiers:
        blockers = eligibility_blockers(
            soldier,
            duty,
            enforce_weapon_qualification=enforce_weapon_qualification,
        )
        if blockers:
            for blocker in blockers:
                blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
            continue

        eligible_count += 1
        has_conflict = any(
            assignment.soldier_id == soldier.id
            and assignment.start_date < duty.end_date
            and duty.start_date < assignment.end_date
            for assignment in existing
        )
        if has_conflict:
            blocker_counts["schedule_conflict"] = blocker_counts.get("schedule_conflict", 0) + 1
        else:
            available_count += 1

    return DutyAvailability(
        eligible_count=eligible_count,
        available_count=available_count,
        blocker_counts=blocker_counts,
    )
