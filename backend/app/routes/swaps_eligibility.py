from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.auth.deps import require_password_changed
from app.db.models import (
    DutyAssignment, DutyType, DutyShift, PersonalConstraint, Soldier,
    SoldierExemption, ExemptionDutyTypeMap, ExemptionType,
)
from app.db.session import get_session
from app.services.eligibility import compute_eligibility_exclusions
from app.services.settings_loader import get_setting, SettingNotFound

router = APIRouter(prefix="/swaps", tags=["swaps"])


class EligibilityResult(BaseModel):
    assignment_id: uuid.UUID
    eligible: bool
    reason: str | None


@router.get("/eligible-duties", response_model=list[EligibilityResult])
def eligible_duties(
    target_soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    """
    For each of the current user's published/active assignments, check whether
    target_soldier_id would be eligible to accept a swap for it.
    """
    today = date.today()
    my_assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.soldier_id == actor.id,
            DutyAssignment.status == "published",
            DutyAssignment.end_date >= today,
        )
    ).scalars().all()

    target = session.get(Soldier, target_soldier_id)
    if target is None:
        return []

    # Collect target's approved constraints
    target_constraints = session.execute(
        select(PersonalConstraint).where(
            PersonalConstraint.soldier_id == target_soldier_id,
            PersonalConstraint.status == "approved",
        )
    ).scalars().all()

    # Collect target's active exemptions
    target_exemptions = session.execute(
        select(SoldierExemption).where(
            SoldierExemption.soldier_id == target_soldier_id,
        )
    ).scalars().all()

    # Eligibility exclusions (mitvahim/alal) — load settings with defaults
    def _setting_int(key: str, default: int) -> int:
        try:
            return int(get_setting(session, key))
        except (SettingNotFound, ValueError):
            return default

    mitvahim_months = _setting_int("eligibility.mitvahim_months", 6)
    alal_months = _setting_int("eligibility.alal_months", 3)

    exclusions = compute_eligibility_exclusions(
        session, [target], mitvahim_months=mitvahim_months, alal_months=alal_months
    )
    excluded_dtype_ids = exclusions.get(target_soldier_id, set())

    # Build exempt duty type set from active exemptions
    exempted_dtype_ids: set[uuid.UUID] = set()
    for ex in target_exemptions:
        if ex.start_date <= today and (ex.end_date is None or ex.end_date >= today):
            rows = session.execute(
                select(ExemptionDutyTypeMap.duty_type_id).where(
                    ExemptionDutyTypeMap.exemption_type_id == ex.exemption_type_id
                )
            ).scalars().all()
            exempted_dtype_ids.update(rows)
            # Check if global exemption
            et = session.get(ExemptionType, ex.exemption_type_id)
            if et and et.is_global:
                all_dt = session.execute(select(DutyType.id)).scalars().all()
                exempted_dtype_ids.update(all_dt)

    results = []
    for a in my_assignments:
        # Check duty type exemption
        if a.duty_type_id in exempted_dtype_ids:
            results.append(EligibilityResult(
                assignment_id=a.id,
                eligible=False,
                reason="פטור מסוג תורנות זו",
            ))
            continue

        # Check eligibility exclusions
        if a.duty_type_id in excluded_dtype_ids:
            results.append(EligibilityResult(
                assignment_id=a.id,
                eligible=False,
                reason='אי-כשירות זמנית (מיטבחים / אל"ל)',
            ))
            continue

        # Check personal constraint overlap
        conflict = next(
            (c for c in target_constraints
             if c.start_date <= a.end_date and c.end_date >= a.start_date),
            None,
        )
        if conflict:
            results.append(EligibilityResult(
                assignment_id=a.id,
                eligible=False,
                reason="אילוץ אישי מאושר בתאריך זה",
            ))
            continue

        results.append(EligibilityResult(assignment_id=a.id, eligible=True, reason=None))

    return results
