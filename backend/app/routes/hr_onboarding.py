from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.db.session import get_session
from app.services.hr_onboarding import OnboardingError, complete_first_login_onboarding

router = APIRouter(prefix="/auth", tags=["hr_onboarding"])


class FirstLoginOnboardingRequest(BaseModel):
    food_type: str | None = None
    food_constraints: str | None = None
    last_mitvahim_date: date | None = None
    last_alal_date: date | None = None
    exemption_requests: list[dict] = []
    personal_constraints: list[dict] = []


class FirstLoginOnboardingResponse(BaseModel):
    food_type: str | None
    food_constraints: str | None
    last_mitvahim_date: date | None
    last_alal_date: date | None
    hr_onboarding_completed_at: str | None


@router.post("/first-login-onboarding", response_model=FirstLoginOnboardingResponse)
def first_login_onboarding(
    body: FirstLoginOnboardingRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FirstLoginOnboardingResponse:
    try:
        soldier = complete_first_login_onboarding(
            session, soldier=user,
            food_type=body.food_type, food_constraints=body.food_constraints,
            last_mitvahim_date=body.last_mitvahim_date, last_alal_date=body.last_alal_date,
            exemption_requests=body.exemption_requests, personal_constraints=body.personal_constraints,
        )
    except OnboardingError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return FirstLoginOnboardingResponse(
        food_type=soldier.food_type, food_constraints=soldier.food_constraints,
        last_mitvahim_date=soldier.last_mitvahim_date, last_alal_date=soldier.last_alal_date,
        hr_onboarding_completed_at=soldier.hr_onboarding_completed_at.isoformat() if soldier.hr_onboarding_completed_at else None,
    )
