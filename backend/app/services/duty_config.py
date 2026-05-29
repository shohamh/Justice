from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyLocation, DutyType, ExemptionDutyTypeMap, ExemptionType, SoldierExemption


class DutyConfigError(Exception):
    """Raised on an invalid duty-config operation."""


def create_duty_type(
    session: Session, *, name: str, score_per_day: Decimal, description: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyType:
    if score_per_day < 0:
        raise DutyConfigError("score_per_day must be >= 0")
    if session.execute(select(DutyType.id).where(DutyType.name == name)).first():
        raise DutyConfigError("name_taken")
    dt = DutyType(name=name, score_per_day=score_per_day, description=description)
    session.add(dt)
    session.flush()
    write_audit(session, actor_id=actor_id, action="duty_type.create", entity_type="duty_type",
                entity_id=dt.id, after={"name": name, "score_per_day": str(score_per_day)})
    return dt


def update_duty_type(
    session: Session, *, duty_type: DutyType, name: str | None, score_per_day: Decimal | None,
    description: str | None, actor_id: uuid.UUID | None = None,
) -> DutyType:
    before = {"name": duty_type.name, "score_per_day": str(duty_type.score_per_day),
              "description": duty_type.description}
    if score_per_day is not None:
        if score_per_day < 0:
            raise DutyConfigError("score_per_day must be >= 0")
        duty_type.score_per_day = score_per_day
    if name is not None and name != duty_type.name:
        if session.execute(select(DutyType.id).where(DutyType.name == name)).first():
            raise DutyConfigError("name_taken")
        duty_type.name = name
    if description is not None:
        duty_type.description = description
    write_audit(session, actor_id=actor_id, action="duty_type.update", entity_type="duty_type",
                entity_id=duty_type.id, before=before,
                after={"name": duty_type.name, "score_per_day": str(duty_type.score_per_day),
                       "description": duty_type.description})
    return duty_type


def set_duty_type_active(
    session: Session, *, duty_type: DutyType, active: bool, actor_id: uuid.UUID | None = None
) -> DutyType:
    before = {"active": duty_type.active}
    duty_type.active = active
    write_audit(session, actor_id=actor_id, action="duty_type.set_active", entity_type="duty_type",
                entity_id=duty_type.id, before=before, after={"active": active})
    return duty_type


def create_location(
    session: Session, *, name: str, base: str | None = None, actor_id: uuid.UUID | None = None
) -> DutyLocation:
    loc = DutyLocation(name=name, base=base)
    session.add(loc)
    session.flush()
    write_audit(session, actor_id=actor_id, action="duty_location.create", entity_type="duty_location",
                entity_id=loc.id, after={"name": name, "base": base})
    return loc


def update_location(
    session: Session, *, location: DutyLocation, name: str | None, base: str | None,
    actor_id: uuid.UUID | None = None,
) -> DutyLocation:
    before = {"name": location.name, "base": location.base}
    if name is not None:
        location.name = name
    if base is not None:
        location.base = base
    write_audit(session, actor_id=actor_id, action="duty_location.update", entity_type="duty_location",
                entity_id=location.id, before=before, after={"name": location.name, "base": location.base})
    return location


def set_location_active(
    session: Session, *, location: DutyLocation, active: bool, actor_id: uuid.UUID | None = None
) -> DutyLocation:
    before = {"active": location.active}
    location.active = active
    write_audit(session, actor_id=actor_id, action="duty_location.set_active", entity_type="duty_location",
                entity_id=location.id, before=before, after={"active": active})
    return location
