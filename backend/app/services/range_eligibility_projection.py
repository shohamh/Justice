from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyType,
)
from app.services.weapon_eligibility import (
    _enforce_enabled,
    _future_windows_by_soldier_and_required_type,
    _is_eligible_from_data,
    _latest_qualification_by_soldier,
    _max_qualification_valid_untils,
    _pending_excusal_disqualifies,
    _profile_valid_until,
)


@dataclass(frozen=True)
class DutyEligibilityFact:
    eligible: bool
    required_range_type: str | None
    qualification_source: str | None
    covered_by_range_date: date | None
    covering_range_type: str | None
    projected_valid_until: date | None
    reason: str | None
    last_qualification_type: str | None
    last_qualification_date: date | None


@dataclass(frozen=True)
class _DutyRequirement:
    id: uuid.UUID
    soldier_id: uuid.UUID
    required_range_type: str | None
    scheduled_date: date


def _requirements_by_id(
    session: Session, *, duty_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, _DutyRequirement]:
    if not duty_ids:
        return {}
    return {
        duty_id: _DutyRequirement(
            id=duty_id,
            soldier_id=soldier_id,
            required_range_type=required_range_type,
            scheduled_date=scheduled_date,
        )
        for duty_id, soldier_id, required_range_type, scheduled_date in session.execute(
            select(
                DutyAssignment.id,
                DutyAssignment.soldier_id,
                DutyType.required_range_type,
                DutyAssignment.start_date,
            )
            .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
            .where(DutyAssignment.id.in_(set(duty_ids)))
        ).all()
    }


def project_duty_eligibility(
    session: Session,
    *,
    soldier_ids: Sequence[uuid.UUID],
    duty_ids: Sequence[uuid.UUID],
    as_of: date | None = None,
) -> dict[tuple[uuid.UUID, uuid.UUID], DutyEligibilityFact]:
    """Project eligibility for supplied duties assigned to supplied soldiers.

    A duty is always evaluated on its scheduled date. ``as_of`` is the lower
    bound for planned main-range windows, defaulting to real ``date.today()``.
    Production callers should therefore pass today's date when they need an
    explicit value; this avoids treating past range events as future coverage.
    """
    future_start = max(date.today(), as_of or date.today())
    unique_soldier_ids = set(soldier_ids)
    requirements = {
        duty_id: requirement
        for duty_id, requirement in _requirements_by_id(session, duty_ids=duty_ids).items()
        if requirement.soldier_id in unique_soldier_ids
    }
    if not unique_soldier_ids or not requirements:
        return {}
    projected_soldier_ids = {requirement.soldier_id for requirement in requirements.values()}

    if not _enforce_enabled(session):
        return {
            (requirement.soldier_id, duty_id): DutyEligibilityFact(
                eligible=True,
                required_range_type=requirement.required_range_type,
                qualification_source="enforcement_disabled",
                covered_by_range_date=None,
                covering_range_type=None,
                projected_valid_until=None,
                reason=None,
                last_qualification_type=None,
                last_qualification_date=None,
            )
            for duty_id, requirement in requirements.items()
        }

    required_types = {
        requirement.required_range_type
        for requirement in requirements.values()
        if requirement.required_range_type is not None
    }
    valid_untils = _max_qualification_valid_untils(
        session,
        soldier_ids=list(projected_soldier_ids),
        required_range_types=list(required_types),
    )
    future_windows = _future_windows_by_soldier_and_required_type(
        session,
        soldier_ids=list(projected_soldier_ids),
        required_range_types=list(required_types),
        disqualify_pending=_pending_excusal_disqualifies(session),
        future_start=future_start,
    )
    latest_qualifications = _latest_qualification_by_soldier(
        session, soldier_ids=list(projected_soldier_ids),
    )

    facts: dict[tuple[uuid.UUID, uuid.UUID], DutyEligibilityFact] = {}
    for duty_id, requirement in requirements.items():
        soldier_id = requirement.soldier_id
        required_range_type = requirement.required_range_type
        if required_range_type is None:
            facts[soldier_id, duty_id] = DutyEligibilityFact(
                eligible=True,
                required_range_type=None,
                qualification_source="not_required",
                covered_by_range_date=None,
                covering_range_type=None,
                projected_valid_until=None,
                reason=None,
                last_qualification_type=None,
                last_qualification_date=None,
            )
            continue
        current_valid_until = valid_untils[soldier_id, required_range_type]
        profile_valid_until = _profile_valid_until(
            session,
            soldier_id=soldier_id,
            required_range_type=required_range_type,
            as_of=requirement.scheduled_date,
        )
        if profile_valid_until is not None:
            current_valid_until = max(current_valid_until or profile_valid_until, profile_valid_until)
        windows = future_windows[soldier_id, required_range_type]
        eligible = _is_eligible_from_data(
            current_best_valid_until=current_valid_until,
            future_windows=windows,
            as_of=requirement.scheduled_date,
        )
        matching_window = next(
            (window for window in windows if window[0] <= requirement.scheduled_date <= window[1]),
            None,
        )
        if current_valid_until is not None and current_valid_until >= requirement.scheduled_date:
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
        latest = latest_qualifications.get(soldier_id)
        facts[soldier_id, duty_id] = DutyEligibilityFact(
            eligible=eligible,
            required_range_type=required_range_type,
            qualification_source=qualification_source,
            covered_by_range_date=covered_by_range_date,
            covering_range_type=covering_range_type,
            projected_valid_until=projected_valid_until,
            reason=None if eligible else "weapon_qualification",
            last_qualification_type=latest[0] if latest else None,
            last_qualification_date=latest[1] if latest else None,
        )
    return facts


def count_ineligible_soldiers_for_duties(
    session: Session,
    *,
    soldier_ids: Sequence[uuid.UUID],
    duty_ids: Sequence[uuid.UUID],
    as_of: date | None = None,
) -> int:
    facts = project_duty_eligibility(
        session, soldier_ids=soldier_ids, duty_ids=duty_ids, as_of=as_of
    )
    return len({soldier_id for (soldier_id, _duty_id), fact in facts.items() if not fact.eligible})
