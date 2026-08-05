from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin, require_password_changed
from app.db.models import RangeLocation, Soldier
from app.db.session import get_session
from app.services import range_locations as svc

router = APIRouter(prefix="/range-locations", tags=["range-locations"])


def require_config_manager(
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> Soldier:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    return user


class RangeLocationOut(BaseModel):
    id: uuid.UUID
    name: str
    active: bool


class CreateRangeLocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _out(loc: RangeLocation) -> RangeLocationOut:
    return RangeLocationOut(id=loc.id, name=loc.name, active=loc.active)


@router.get("", response_model=list[RangeLocationOut])
def list_range_locations(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[RangeLocationOut]:
    return [_out(loc) for loc in session.execute(select(RangeLocation)).scalars().all()]


@router.post("", response_model=RangeLocationOut, status_code=status.HTTP_201_CREATED)
def create_range_location(
    body: CreateRangeLocationRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> RangeLocationOut:
    loc = svc.create_range_location(session, name=body.name, actor_id=user.id)
    session.commit()
    session.refresh(loc)
    return _out(loc)
