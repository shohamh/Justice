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
    usage_count: int
    can_delete: bool


class CreateRangeLocationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdateRangeLocationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None


def _out(loc: RangeLocation, usage_count: int) -> RangeLocationOut:
    return RangeLocationOut(id=loc.id, name=loc.name, active=loc.active,
                            usage_count=usage_count, can_delete=usage_count == 0)


@router.get("", response_model=list[RangeLocationOut])
def list_range_locations(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)
) -> list[RangeLocationOut]:
    locations = session.execute(select(RangeLocation)).scalars().all()
    return [_out(loc, svc.usage_count(session, loc.id)) for loc in locations]


@router.post("", response_model=RangeLocationOut, status_code=status.HTTP_201_CREATED)
def create_range_location(
    body: CreateRangeLocationRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> RangeLocationOut:
    loc = svc.create_range_location(session, name=body.name, actor_id=user.id)
    session.commit()
    session.refresh(loc)
    return _out(loc, 0)


@router.patch("/{location_id}", response_model=RangeLocationOut)
def update_range_location(
    location_id: uuid.UUID,
    body: UpdateRangeLocationRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> RangeLocationOut:
    location = session.get(RangeLocation, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="location_not_found")
    if not body.model_fields_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no_changes")
    loc = svc.update_range_location(
        session, location=location, name=body.name, active=body.active, actor_id=user.id,
    )
    session.commit()
    session.refresh(loc)
    return _out(loc, svc.usage_count(session, loc.id))


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_range_location(
    location_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_config_manager),
) -> None:
    location = session.get(RangeLocation, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="location_not_found")
    try:
        svc.delete_range_location(session, location=location, actor_id=user.id)
    except svc.RangeLocationInUseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
