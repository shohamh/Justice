from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExemptionRequest, ExemptionType, NotificationType, PersonalConstraint, Soldier, SoldierHrProfile
from app.services.notifications import notify_commanders_of_request
from app.services.registration import validate_personal_constraint
from app.services.soldiers import SoldierValidationError, validate_soldier_dates

# Mirrors the `food_type` Enum column in app/db/models.py. Kept as a plain
# tuple rather than introspecting the column, to keep this validation free of
# SQLAlchemy metadata coupling.
_VALID_FOOD_TYPES = ("regular", "vegetarian", "vegan", "gluten_free", "kosher_le_mehadrin")


class OnboardingError(Exception):
    pass


def complete_first_login_onboarding(
    session: Session,
    *,
    soldier: Soldier,
    food_type: str | None,
    food_constraints: str | None,
    last_mitvahim_date: date | None,
    last_alal_date: date | None,
    exemption_requests: list[dict],
    personal_constraints: list[dict],
) -> Soldier:
    # Eligibility gate (C3): the route only gated on require_password_changed,
    # so any soldier — HR-linked or not, already onboarded or not — could call
    # this repeatedly and bypass the checks below. Only a soldier who came
    # through HR sync and hasn't completed onboarding yet is eligible.
    hr_profile = session.execute(
        select(SoldierHrProfile.id).where(SoldierHrProfile.soldier_id == soldier.id)
    ).first()
    if hr_profile is None or soldier.hr_onboarding_completed_at is not None:
        raise OnboardingError("not_eligible")

    if food_type is not None and food_type not in _VALID_FOOD_TYPES:
        raise OnboardingError("invalid_food_type")

    for er in exemption_requests:
        exemption_type_id_raw = er.get("exemption_type_id")
        start_date_raw = er.get("start_date")
        end_date_raw = er.get("end_date")
        if not exemption_type_id_raw:
            raise OnboardingError("exemption_missing_fields")
        if end_date_raw and not start_date_raw:
            raise OnboardingError("start_date_required")
        try:
            exemption_type_id = uuid.UUID(str(exemption_type_id_raw))
        except ValueError as exc:
            raise OnboardingError("exemption_missing_fields") from exc
        et = session.get(ExemptionType, exemption_type_id)
        if et is None:
            raise OnboardingError("exemption_type_not_found")
        if et.is_commander_exemption:
            raise OnboardingError("commander_exemption_not_requestable")
        if end_date_raw and start_date_raw and end_date_raw < start_date_raw:
            raise OnboardingError("bad_date_range")

    for pc in personal_constraints:
        try:
            validate_personal_constraint(pc)
        except ValueError as exc:
            raise OnboardingError(str(exc)) from exc

    soldier.food_type = food_type
    soldier.food_constraints = food_constraints
    soldier.last_mitvahim_date = last_mitvahim_date
    soldier.last_alal_date = last_alal_date

    try:
        validate_soldier_dates(soldier)
    except SoldierValidationError as exc:
        raise OnboardingError(str(exc)) from exc

    created_requests: list[ExemptionRequest] = []
    for er in exemption_requests:
        req = ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=uuid.UUID(str(er["exemption_type_id"])),
            start_date=er.get("start_date") or None,
            end_date=er.get("end_date") or None,
            reason=er.get("reason"),
            status="pending_commander",
        )
        session.add(req)
        created_requests.append(req)

    for pc in personal_constraints:
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc.get("reason"),
            status="pending_commander",
        ))

    session.flush()  # assign IDs to the new ExemptionRequest rows before notifying

    for req in created_requests:
        notify_commanders_of_request(
            session,
            soldier_id=soldier.id,
            type=NotificationType.exemption_request_pending,
            title="בקשת פטור חדשה",
            body=req.reason,
            reference_type="exemption_request",
            reference_id=req.id,
            actor_id=soldier.id,
            target_tab="exemptions",
        )

    if last_mitvahim_date is not None or last_alal_date is not None:
        from app.services.duty_eligibility_watch import recheck_soldier_assignments
        recheck_soldier_assignments(session, soldier.id)

    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    session.flush()
    return soldier
