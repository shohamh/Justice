from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

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
from app.services.eligibility import DutyTypeRequirements, _is_eligible
from app.services.range_eligibility_projection import DutyEligibilityFact, project_duty_eligibility
from app.services.ranges import _validity_days
from app.services.single_flight import SingleFlight


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
    duty_eligibility: dict[uuid.UUID, DutyEligibilityFact]


@dataclass(frozen=True)
class _IneligibleCandidates:
    soldiers: list[tuple[Soldier, HierarchyNode]]
    valid_qualifications: dict[uuid.UUID, tuple[QualificationSummary, ...]]
    upcoming_weapon_duties: dict[uuid.UUID, tuple[UpcomingWeaponDuty, ...]]
    duty_eligibility: dict[tuple[uuid.UUID, uuid.UUID], DutyEligibilityFact]


# Every Soldier attribute ``eligibility._ineligibility_reason`` reads (with no
# rank override). Keep in sync with that function: a missing field would make
# soldiers with different values share one structural-eligibility verdict.
_STRUCTURAL_ELIGIBILITY_FIELDS = (
    "gender",
    "last_mitvahim_date",
    "last_alal_date",
    "rank",
    "mandatory_end_date",
    "is_officer",
    "bahad1_graduate",
    "has_military_driving_license",
    "military_driving_license_expiry",
)


def _structural_profile(soldier: Any) -> tuple[Any, ...]:
    return tuple(getattr(soldier, field) for field in _STRUCTURAL_ELIGIBILITY_FIELDS)


def _scope_clause(roots: set[uuid.UUID] | None):
    if roots is None:
        return None
    if not roots:
        return False
    return or_(*(HierarchyNode.path_ids.any(root_id) for root_id in roots))  # type: ignore[arg-type]


def _valid_qualifications_by_soldier(
    session: Session,
    *,
    soldiers: list[Soldier],
    as_of: date,
) -> dict[uuid.UUID, tuple[QualificationSummary, ...]]:
    """Match the existing qualification boundary: valid_until covers as_of inclusively."""
    if not soldiers:
        return {}
    profile_rows = {
        soldier.id: (soldier.last_mitvahim_date, soldier.last_alal_date)
        for soldier in soldiers
    }
    qualifications_by_soldier: defaultdict[uuid.UUID, list[QualificationSummary]] = defaultdict(
        list
    )
    rows = session.execute(
        select(
            SoldierRangeQualification.soldier_id,
            SoldierRangeQualification.range_type,
            SoldierRangeQualification.valid_until,
        )
        .where(
            SoldierRangeQualification.soldier_id.in_(profile_rows),
            SoldierRangeQualification.valid_until >= as_of,
        )
        .order_by(SoldierRangeQualification.range_type, SoldierRangeQualification.valid_until)
    ).all()
    for soldier_id, range_type, valid_until in rows:
        qualifications_by_soldier[soldier_id].append(
            QualificationSummary(
                range_type=range_type, valid_until=valid_until
            )
        )
    profile_validity_days = {
        range_type: _validity_days(session, range_type)
        for range_type, field_index in ((RangeType.live, 0), (RangeType.alal, 1))
        if any(profile_dates[field_index] is not None for profile_dates in profile_rows.values())
    }
    for soldier_id, (last_mitvahim_date, last_alal_date) in profile_rows.items():
        for range_type, completed_date in (
            (RangeType.live, last_mitvahim_date),
            (RangeType.alal, last_alal_date),
        ):
            if completed_date is None:
                continue
            valid_until = completed_date + timedelta(days=profile_validity_days[range_type])
            if valid_until >= as_of:
                qualifications_by_soldier[soldier_id].append(
                    QualificationSummary(range_type=range_type, valid_until=valid_until)
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


def _has_matching_range_for_each_duty(
    duties: tuple[UpcomingWeaponDuty, ...],
    ranges: tuple[UpcomingMatchingRange, ...],
) -> bool:
    """Require a scheduled matching range for every future weapon duty."""
    return bool(duties) and all(
        any(
            scheduled.range_type == duty.required_range_type
            and scheduled.date <= duty.start_date
            for scheduled in ranges
        )
        for duty in duties
    )


def _weapon_eligible_soldier_ids(
    session: Session,
    *,
    soldiers: Sequence[Any],
    as_of: date,
    profile_key: Callable[[Any], tuple[Any, ...]] = _structural_profile,
) -> set[uuid.UUID]:
    """Return whether the soldier can structurally serve any weapon duty.

    Range dates are deliberately removed from this check: this panel is meant
    to identify soldiers who need a current range, so lacking that range must
    not make every weapon duty appear structurally unavailable.

    ``soldiers`` may be ``Soldier`` entities or rows exposing the same
    attributes; ``profile_key`` must return the values of
    ``_STRUCTURAL_ELIGIBILITY_FIELDS`` for one of them.
    """
    duty_types = session.execute(
        select(DutyType).where(
            DutyType.active.is_(True),
            or_(DutyType.requires_weapon.is_(True), DutyType.required_range_type.is_not(None)),
        )
    ).scalars().all()
    # ``_is_eligible`` is a pure function of these attributes, so evaluating
    # one representative per distinct combination is exact and turns
    # duty types x soldiers into duty types x combinations.
    ids_by_profile: defaultdict[tuple[Any, ...], list[uuid.UUID]] = defaultdict(list)
    representatives: dict[tuple[Any, ...], Any] = {}
    for soldier in soldiers:
        profile = profile_key(soldier)
        ids_by_profile[profile].append(soldier.id)
        representatives.setdefault(profile, soldier)
    pending = set(representatives)
    eligible_soldier_ids: set[uuid.UUID] = set()
    for duty_type in duty_types:
        raw_requirements = dict(duty_type.requirements or {})
        raw_requirements["requires_mitvahim"] = False
        raw_requirements["requires_alal"] = False
        try:
            requirements = DutyTypeRequirements.model_validate(raw_requirements)
        except Exception:
            continue
        for profile in list(pending):
            if _is_eligible(
                representatives[profile],
                requirements,
                mitvahim_months=6,
                alal_months=3,
                today=as_of,
            ):
                eligible_soldier_ids.update(ids_by_profile[profile])
                pending.discard(profile)
    return eligible_soldier_ids


def _ineligible_candidates(
    session: Session,
    *,
    roots: set[uuid.UUID] | None,
    as_of: date,
) -> _IneligibleCandidates:
    statement = select(Soldier, HierarchyNode).join(
        HierarchyNode, Soldier.hierarchy_node_id == HierarchyNode.id
    )
    scope_clause = _scope_clause(roots)
    if scope_clause is not None:
        statement = statement.where(scope_clause)

    scoped_soldiers = session.execute(statement).all()
    weapon_eligible_soldier_ids = _weapon_eligible_soldier_ids(
        session,
        soldiers=[soldier for soldier, _node in scoped_soldiers],
        as_of=as_of,
    )
    valid_qualifications_by_soldier = _valid_qualifications_by_soldier(
        session,
        soldiers=[soldier for soldier, _node in scoped_soldiers],
        as_of=as_of,
    )
    upcoming_weapon_duties_by_soldier = _upcoming_weapon_duties_by_soldier(
        session,
        soldier_ids={soldier.id for soldier, _node in scoped_soldiers},
        as_of=as_of,
    )
    duty_eligibility = project_duty_eligibility(
        session,
        soldier_ids=[soldier.id for soldier, _node in scoped_soldiers],
        duty_ids=[
            duty.assignment_id
            for duties in upcoming_weapon_duties_by_soldier.values()
            for duty in duties
        ],
        as_of=as_of,
    )
    ineligible_soldiers = [
        (soldier, node)
        for soldier, node in scoped_soldiers
        if soldier.id in weapon_eligible_soldier_ids
        if soldier.id not in valid_qualifications_by_soldier
        or any(
            not duty_eligibility[soldier.id, duty.assignment_id].eligible
            for duty in upcoming_weapon_duties_by_soldier.get(soldier.id, ())
        )
    ]
    return _IneligibleCandidates(
        soldiers=ineligible_soldiers,
        valid_qualifications=valid_qualifications_by_soldier,
        upcoming_weapon_duties=upcoming_weapon_duties_by_soldier,
        duty_eligibility=duty_eligibility,
    )


# Every Soldier attribute the count path reads: ``_is_eligible`` (structural
# requirements) plus the profile range dates used by
# ``_valid_qualifications_by_soldier`` (both already in the structural set).
# Loading these columns as plain rows instead of full ORM entities was most of
# the count's cost at scale.
_COUNT_SOLDIER_COLUMNS = (
    Soldier.id,
    *(getattr(Soldier, field) for field in _STRUCTURAL_ELIGIBILITY_FIELDS),
)


def _count_row_profile(row: Any) -> tuple[Any, ...]:
    """Structural profile of a ``_COUNT_SOLDIER_COLUMNS`` row: every column but id.

    Positional slicing is several times cheaper than nine by-name lookups on a
    SQLAlchemy ``Row`` across 20k soldiers.
    """
    return tuple(row)[1:]


def count_ineligible_soldiers(
    session: Session,
    *,
    roots: set[uuid.UUID] | None,
    as_of: date,
) -> int:
    """Count the same scoped eligibility results without loading list-only range details."""
    statement = select(*_COUNT_SOLDIER_COLUMNS).join(
        HierarchyNode, Soldier.hierarchy_node_id == HierarchyNode.id
    )
    scope_clause = _scope_clause(roots)
    if scope_clause is not None:
        statement = statement.where(scope_clause)
    # Lightweight rows exposing the same attribute names the helpers read.
    scoped_soldiers: list[Any] = list(session.execute(statement).all())
    weapon_eligible_ids = _weapon_eligible_soldier_ids(
        session, soldiers=scoped_soldiers, as_of=as_of, profile_key=_count_row_profile
    )
    eligible_soldiers = [
        soldier for soldier in scoped_soldiers if soldier.id in weapon_eligible_ids
    ]
    valid_qualifications = _valid_qualifications_by_soldier(
        session, soldiers=eligible_soldiers, as_of=as_of
    )
    without_current_qualification = len(eligible_soldiers) - sum(
        soldier.id in valid_qualifications for soldier in eligible_soldiers
    )
    qualified_ids = {soldier.id for soldier in eligible_soldiers if soldier.id in valid_qualifications}
    if not qualified_ids:
        return without_current_qualification

    future_duties = _upcoming_weapon_duties_by_soldier(
        session, soldier_ids=qualified_ids, as_of=as_of
    )
    duty_ids = [duty.assignment_id for duties in future_duties.values() for duty in duties]
    duty_eligibility = project_duty_eligibility(
        session, soldier_ids=list(qualified_ids), duty_ids=duty_ids, as_of=as_of
    )
    return without_current_qualification + sum(
        any(not duty_eligibility[soldier_id, duty.assignment_id].eligible for duty in duties)
        for soldier_id, duties in future_duties.items()
    )


_count_flight: SingleFlight[int] = SingleFlight()


def count_ineligible_soldiers_coalesced(
    session: Session,
    *,
    roots: set[uuid.UUID] | None,
    as_of: date,
) -> int:
    """``count_ineligible_soldiers``, sharing one computation between concurrent
    callers with the same scope and date.

    Every shell load asks for this count at once (5 simultaneous admin loads
    ran 5 identical CPU-bound counts that serialized on the GIL). The key holds
    the caller's scope roots, so callers with different scopes never share a
    result, and nothing is kept after the computation ends.
    """
    key = (None if roots is None else frozenset(roots), as_of)
    return _count_flight.do(
        key, lambda: count_ineligible_soldiers(session, roots=roots, as_of=as_of)
    )


def list_ineligible_soldiers(
    session: Session,
    *,
    roots: set[uuid.UUID] | None,
    as_of: date,
) -> list[IneligibleSoldierRecord]:
    """Return scoped soldiers lacking a current qualification or future duty eligibility."""
    candidates = _ineligible_candidates(session, roots=roots, as_of=as_of)
    ineligible_soldiers = candidates.soldiers
    valid_qualifications_by_soldier = candidates.valid_qualifications
    upcoming_weapon_duties_by_soldier = candidates.upcoming_weapon_duties
    duty_eligibility = candidates.duty_eligibility
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
                has_upcoming_matching_range=_has_matching_range_for_each_duty(
                    upcoming_weapon_duties, upcoming_matching_ranges
                ),
                upcoming_weapon_duties=upcoming_weapon_duties,
                upcoming_matching_ranges=upcoming_matching_ranges,
                duty_eligibility={
                    duty.assignment_id: duty_eligibility[soldier.id, duty.assignment_id]
                    for duty in upcoming_weapon_duties
                },
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
