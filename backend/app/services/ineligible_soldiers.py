from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyType,
    HierarchyNode,
    RangeAssignment,
    RangeEvent,
    RangeEventStatus,
    RangeType,
    Soldier,
    SoldierRangeQualification,
)


@dataclass(frozen=True)
class QualificationSummary:
    range_type: RangeType
    valid_until: date


@dataclass(frozen=True)
class UpcomingWeaponDuty:
    assignment_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_type_name: str
    start_date: date
    end_date: date
    required_range_type: RangeType


@dataclass(frozen=True)
class UpcomingMatchingRange:
    event_id: uuid.UUID
    range_type: RangeType
    date: date


@dataclass(frozen=True)
class IneligibleSoldierRecord:
    soldier_id: uuid.UUID
    soldier_name: str
    personal_number: str
    hierarchy_node_id: uuid.UUID
    hierarchy_node_name: str
    hierarchy_path_ids: tuple[uuid.UUID, ...]
    valid_qualifications: tuple[QualificationSummary, ...]
    has_upcoming_weapon_duty: bool
    has_upcoming_matching_range: bool
    upcoming_weapon_duties: tuple[UpcomingWeaponDuty, ...]
    upcoming_matching_ranges: tuple[UpcomingMatchingRange, ...]


def _scope_clause(roots: set[uuid.UUID] | None):
    if roots is None:
        return None
    if not roots:
        return False
    return or_(*(HierarchyNode.path_ids.any(root_id) for root_id in roots))  # type: ignore[arg-type]


def _valid_qualifications_by_soldier(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID],
    as_of: date,
) -> dict[uuid.UUID, tuple[QualificationSummary, ...]]:
    """Match the existing qualification boundary: valid_until covers as_of inclusively."""
    if not soldier_ids:
        return {}
    qualifications_by_soldier: defaultdict[uuid.UUID, list[QualificationSummary]] = defaultdict(
        list
    )
    qualifications = (
        session.execute(
            select(SoldierRangeQualification)
            .where(
                SoldierRangeQualification.soldier_id.in_(soldier_ids),
                SoldierRangeQualification.valid_until >= as_of,
            )
            .order_by(SoldierRangeQualification.range_type, SoldierRangeQualification.valid_until)
        )
        .scalars()
        .all()
    )
    for qualification in qualifications:
        qualifications_by_soldier[qualification.soldier_id].append(
            QualificationSummary(
                range_type=qualification.range_type, valid_until=qualification.valid_until
            )
        )
    return {
        soldier_id: tuple(summaries) for soldier_id, summaries in qualifications_by_soldier.items()
    }


def _upcoming_weapon_duties_by_soldier(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID],
    as_of: date,
) -> dict[uuid.UUID, tuple[UpcomingWeaponDuty, ...]]:
    if not soldier_ids:
        return {}
    duties_by_soldier: defaultdict[uuid.UUID, list[UpcomingWeaponDuty]] = defaultdict(list)
    rows = session.execute(
        select(DutyAssignment, DutyType)
        .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
        .where(
            DutyAssignment.soldier_id.in_(soldier_ids),
            DutyAssignment.status == "published",
            DutyAssignment.start_date >= as_of,
            DutyType.required_range_type.is_not(None),
        )
        .order_by(DutyAssignment.soldier_id, DutyAssignment.start_date, DutyAssignment.id)
    ).all()
    for assignment, duty_type in rows:
        duties_by_soldier[assignment.soldier_id].append(
            UpcomingWeaponDuty(
                assignment_id=assignment.id,
                duty_type_id=duty_type.id,
                duty_type_name=duty_type.name,
                start_date=assignment.start_date,
                end_date=assignment.end_date,
                required_range_type=duty_type.required_range_type,
            )
        )
    return {soldier_id: tuple(duties) for soldier_id, duties in duties_by_soldier.items()}


def _upcoming_matching_ranges_by_soldier(
    session: Session,
    *,
    required_range_types_by_soldier: dict[uuid.UUID, set[RangeType]],
    as_of: date,
) -> dict[uuid.UUID, tuple[UpcomingMatchingRange, ...]]:
    all_required_range_types = set().union(*required_range_types_by_soldier.values())
    if not all_required_range_types:
        return {}
    ranges_by_soldier: defaultdict[uuid.UUID, list[UpcomingMatchingRange]] = defaultdict(list)
    rows = session.execute(
        select(RangeEvent, RangeAssignment.soldier_id)
        .join(RangeAssignment, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id.in_(required_range_types_by_soldier),
            RangeAssignment.is_draft.is_(False),
            RangeEvent.status == RangeEventStatus.planned,
            RangeEvent.date >= as_of,
            RangeEvent.range_type.in_(all_required_range_types),
        )
        .order_by(RangeAssignment.soldier_id, RangeEvent.date, RangeEvent.id)
    ).all()
    for event, soldier_id in rows:
        if event.range_type in required_range_types_by_soldier[soldier_id]:
            ranges_by_soldier[soldier_id].append(
                UpcomingMatchingRange(
                    event_id=event.id, range_type=event.range_type, date=event.date
                )
            )
    return {soldier_id: tuple(ranges) for soldier_id, ranges in ranges_by_soldier.items()}


def list_ineligible_soldiers(
    session: Session,
    *,
    roots: set[uuid.UUID] | None,
    as_of: date,
) -> list[IneligibleSoldierRecord]:
    """Return scoped soldiers with no qualification whose validity covers as_of."""
    statement = select(Soldier, HierarchyNode).join(
        HierarchyNode, Soldier.hierarchy_node_id == HierarchyNode.id
    )
    scope_clause = _scope_clause(roots)
    if scope_clause is not None:
        statement = statement.where(scope_clause)

    scoped_soldiers = session.execute(statement).all()
    valid_qualifications_by_soldier = _valid_qualifications_by_soldier(
        session,
        soldier_ids={soldier.id for soldier, _node in scoped_soldiers},
        as_of=as_of,
    )
    ineligible_soldiers = [
        (soldier, node)
        for soldier, node in scoped_soldiers
        if soldier.id not in valid_qualifications_by_soldier
    ]
    upcoming_weapon_duties_by_soldier = _upcoming_weapon_duties_by_soldier(
        session,
        soldier_ids={soldier.id for soldier, _node in ineligible_soldiers},
        as_of=as_of,
    )
    upcoming_matching_ranges_by_soldier = _upcoming_matching_ranges_by_soldier(
        session,
        required_range_types_by_soldier={
            soldier_id: {duty.required_range_type for duty in duties}
            for soldier_id, duties in upcoming_weapon_duties_by_soldier.items()
        },
        as_of=as_of,
    )

    records: list[IneligibleSoldierRecord] = []
    for soldier, node in ineligible_soldiers:
        valid_qualifications = valid_qualifications_by_soldier.get(soldier.id, ())
        upcoming_weapon_duties = upcoming_weapon_duties_by_soldier.get(soldier.id, ())
        upcoming_matching_ranges = upcoming_matching_ranges_by_soldier.get(soldier.id, ())
        records.append(
            IneligibleSoldierRecord(
                soldier_id=soldier.id,
                soldier_name=soldier.full_name,
                personal_number=soldier.personal_number,
                hierarchy_node_id=node.id,
                hierarchy_node_name=node.name,
                hierarchy_path_ids=tuple(node.path_ids),
                valid_qualifications=valid_qualifications,
                has_upcoming_weapon_duty=bool(upcoming_weapon_duties),
                has_upcoming_matching_range=bool(upcoming_matching_ranges),
                upcoming_weapon_duties=upcoming_weapon_duties,
                upcoming_matching_ranges=upcoming_matching_ranges,
            )
        )

    return sorted(
        records,
        key=lambda record: (
            tuple(str(node_id) for node_id in record.hierarchy_path_ids),
            record.soldier_name.casefold(),
            str(record.soldier_id),
        ),
    )
