from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, Soldier
from app.db.session import get_session
from app.services.eligibility import check_soldier_for_assignment

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

    if session.get(Soldier, target_soldier_id) is None:
        return []

    results = []
    for a in my_assignments:
        eligible, reason = check_soldier_for_assignment(session, target_soldier_id, a.id)
        results.append(EligibilityResult(assignment_id=a.id, eligible=eligible, reason=reason))
    return results
