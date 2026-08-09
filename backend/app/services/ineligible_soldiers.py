from __future__ import annotations

import uuid
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


def _valid_qualifications(
    session: Session, *, soldier_id: uuid.UUID, as_of: date,
) -> tuple[QualificationSummary, ...]:
    """Match the existing qualification boundary: valid_until covers as_of inclusively."""
    qualifications = session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier_id,
            SoldierRangeQualification.valid_until >= as_of,
        ).order_by(SoldierRangeQualification.range_type, SoldierRangeQualification.valid_until)
    ).scalars().all()
    return tuple(
        QualificationSummary(range_type=qualification.range_type, valid_until=qualification.valid_until)
        for qualification in qualifications
    )


def _upcoming_weapon_duties(
    session: Session, *, soldier_id: uuid.UUID, as_of: date,
) -> tuple[UpcomingWeaponDuty, ...]:
    rows = session.execute(
        select(DutyAssignment, DutyType)
        .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
        .where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.status == "published",
            DutyAssignment.start_date >= as_of,
            DutyType.required_range_type.is_not(None),
        )
        .order_by(DutyAssignment.start_date, DutyAssignment.id)
    ).all()
    return tuple(
        UpcomingWeaponDuty(
            assignment_id=assignment.id,
            duty_type_id=duty_type.id,
            duty_type_name=duty_type.name,
            start_date=assignment.start_date,
            end_date=assignment.end_date,
            required_range_type=duty_type.required_range_type,
        )
        for assignment, duty_type in rows
    )


def _upcoming_matching_ranges(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    required_range_types: set[RangeType],
    as_of: date,
) -> tuple[UpcomingMatchingRange, ...]:
    if not required_range_types:
        return ()
    rows = session.execute(
        select(RangeEvent)
        .join(RangeAssignment, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier_id,
            RangeAssignment.is_draft.is_(False),
            RangeEvent.status == RangeEventStatus.planned,
            RangeEvent.date >= as_of,
            RangeEvent.range_type.in_(required_range_types),
        )
        .order_by(RangeEvent.date, RangeEvent.id)
    ).scalars().all()
    return tuple(
        UpcomingMatchingRange(event_id=event.id, range_type=event.range_type, date=event.date)
        for event in rows
    )


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

    records: list[IneligibleSoldierRecord] = []
    for soldier, node in session.execute(statement).all():
        valid_qualifications = _valid_qualifications(session, soldier_id=soldier.id, as_of=as_of)
        if valid_qualifications:
            continue
        upcoming_weapon_duties = _upcoming_weapon_duties(session, soldier_id=soldier.id, as_of=as_of)
        upcoming_matching_ranges = _upcoming_matching_ranges(
            session,
            soldier_id=soldier.id,
            required_range_types={duty.required_range_type for duty in upcoming_weapon_duties},
            as_of=as_of,
        )
        records.append(IneligibleSoldierRecord(
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
        ))

    return sorted(
        records,
        key=lambda record: (
            tuple(str(node_id) for node_id in record.hierarchy_path_ids),
            record.soldier_name.casefold(),
            str(record.soldier_id),
        ),
    )
