from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import ExemptionRequest, ExemptionType, PersonalConstraint, Soldier
from app.services.registration import validate_personal_constraint


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

    for er in exemption_requests:
        session.add(ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=uuid.UUID(str(er["exemption_type_id"])),
            start_date=er.get("start_date") or None,
            end_date=er.get("end_date") or None,
            reason=er.get("reason"),
            status="pending_commander",
        ))

    for pc in personal_constraints:
        session.add(PersonalConstraint(
            soldier_id=soldier.id,
            start_date=pc["start_date"],
            end_date=pc["end_date"],
            reason=pc.get("reason"),
            status="pending_commander",
        ))

    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    session.flush()
    return soldier
