from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    SoldierExemption,
)


class DutyConfigError(Exception):
    """Raised on an invalid duty-config operation."""


def create_duty_type(
    session: Session,
    *,
    name: str,
    score_per_day: Decimal,
    description: str | None = None,
    reserve_ratio: Decimal = Decimal("0.000"),
    reserve_minimum: int = 0,
    actor_id: uuid.UUID | None = None,
) -> DutyType:
    if score_per_day < 0:
        raise DutyConfigError("score_per_day must be >= 0")
    if session.execute(select(DutyType.id).where(DutyType.name == name)).first():
        raise DutyConfigError("name_taken")
    dt = DutyType(
        name=name,
        score_per_day=score_per_day,
        description=description,
        reserve_ratio=reserve_ratio,
        reserve_minimum=reserve_minimum,
    )
    session.add(dt)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_type.create",
        entity_type="duty_type",
        entity_id=dt.id,
        after={
            "name": name,
            "score_per_day": str(score_per_day),
            "reserve_ratio": str(reserve_ratio),
            "reserve_minimum": reserve_minimum,
        },
    )
    return dt


def update_duty_type(
    session: Session,
    *,
    duty_type: DutyType,
    name: str | None,
    score_per_day: Decimal | None,
    description: str | None,
    actor_id: uuid.UUID | None = None,
    requirements: dict | None = None,
    reserve_ratio: Decimal | None = None,
    reserve_minimum: int | None = None,
) -> DutyType:
    before = {
        "name": duty_type.name,
        "score_per_day": str(duty_type.score_per_day),
        "description": duty_type.description,
    }
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
    if requirements is not None:
        from app.services.eligibility import DutyTypeRequirements
        DutyTypeRequirements.model_validate(requirements)  # validate shape
        duty_type.requirements = requirements
    if reserve_ratio is not None:
        before["reserve_ratio"] = str(duty_type.reserve_ratio)
        duty_type.reserve_ratio = reserve_ratio
    if reserve_minimum is not None:
        before["reserve_minimum"] = duty_type.reserve_minimum
        duty_type.reserve_minimum = reserve_minimum
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_type.update",
        entity_type="duty_type",
        entity_id=duty_type.id,
        before=before,
        after={
            "name": duty_type.name,
            "score_per_day": str(duty_type.score_per_day),
            "description": duty_type.description,
            "reserve_ratio": str(duty_type.reserve_ratio),
            "reserve_minimum": duty_type.reserve_minimum,
        },
    )
    return duty_type


def set_duty_type_active(
    session: Session, *, duty_type: DutyType, active: bool, actor_id: uuid.UUID | None = None
) -> DutyType:
    before = {"active": duty_type.active}
    duty_type.active = active
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_type.set_active",
        entity_type="duty_type",
        entity_id=duty_type.id,
        before=before,
        after={"active": active},
    )
    return duty_type


def create_location(
    session: Session, *, name: str, base: str | None = None, actor_id: uuid.UUID | None = None
) -> DutyLocation:
    loc = DutyLocation(name=name, base=base)
    session.add(loc)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_location.create",
        entity_type="duty_location",
        entity_id=loc.id,
        after={"name": name, "base": base},
    )
    return loc


def update_location(
    session: Session,
    *,
    location: DutyLocation,
    name: str | None,
    base: str | None,
    actor_id: uuid.UUID | None = None,
) -> DutyLocation:
    before = {"name": location.name, "base": location.base}
    if name is not None:
        location.name = name
    if base is not None:
        location.base = base
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_location.update",
        entity_type="duty_location",
        entity_id=location.id,
        before=before,
        after={"name": location.name, "base": location.base},
    )
    return location


def set_location_active(
    session: Session, *, location: DutyLocation, active: bool, actor_id: uuid.UUID | None = None
) -> DutyLocation:
    before = {"active": location.active}
    location.active = active
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_location.set_active",
        entity_type="duty_location",
        entity_id=location.id,
        before=before,
        after={"active": active},
    )
    return location


def create_exemption_type(
    session: Session,
    *,
    name: str,
    description: str | None = None,
    is_global: bool = False,
    is_medical: bool = False,
    actor_id: uuid.UUID | None = None,
) -> ExemptionType:
    if session.execute(select(ExemptionType.id).where(ExemptionType.name == name)).first():
        raise DutyConfigError("name_taken")
    et = ExemptionType(name=name, description=description, is_global=is_global, is_medical=is_medical)
    session.add(et)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_type.create",
        entity_type="exemption_type",
        entity_id=et.id,
        after={"name": name, "is_global": is_global, "is_medical": is_medical},
    )
    return et


def update_exemption_type(
    session: Session,
    *,
    exemption_type: ExemptionType,
    name: str | None,
    description: str | None,
    is_global: bool | None = None,
    is_medical: bool | None = None,
    actor_id: uuid.UUID | None = None,
) -> ExemptionType:
    before = {"name": exemption_type.name, "description": exemption_type.description, "is_global": exemption_type.is_global, "is_medical": exemption_type.is_medical}
    if name is not None and name != exemption_type.name:
        if session.execute(select(ExemptionType.id).where(ExemptionType.name == name)).first():
            raise DutyConfigError("name_taken")
        exemption_type.name = name
    if description is not None:
        exemption_type.description = description
    if is_global is not None:
        exemption_type.is_global = is_global
    if is_medical is not None:
        exemption_type.is_medical = is_medical
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_type.update",
        entity_type="exemption_type",
        entity_id=exemption_type.id,
        before=before,
        after={"name": exemption_type.name, "description": exemption_type.description, "is_global": exemption_type.is_global, "is_medical": exemption_type.is_medical},
    )
    return exemption_type


def delete_exemption_type(
    session: Session, *, exemption_type: ExemptionType, actor_id: uuid.UUID | None = None
) -> None:
    granted = session.execute(
        select(SoldierExemption.id)
        .where(SoldierExemption.exemption_type_id == exemption_type.id)
        .limit(1)
    ).first()
    if granted is not None:
        raise DutyConfigError("exemption_type_in_use")
    # map rows cascade via ON DELETE CASCADE
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_type.delete",
        entity_type="exemption_type",
        entity_id=exemption_type.id,
        before={"name": exemption_type.name},
    )
    session.delete(exemption_type)


def map_exemption_to_duty_type(
    session: Session,
    *,
    exemption_type_id: uuid.UUID,
    duty_type_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    if session.get(ExemptionType, exemption_type_id) is None:
        raise DutyConfigError("exemption_type_not_found")
    if session.get(DutyType, duty_type_id) is None:
        raise DutyConfigError("duty_type_not_found")
    exists = session.get(ExemptionDutyTypeMap, (exemption_type_id, duty_type_id))
    if exists is not None:
        return  # idempotent
    session.add(
        ExemptionDutyTypeMap(exemption_type_id=exemption_type_id, duty_type_id=duty_type_id)
    )
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_map.add",
        entity_type="exemption_type",
        entity_id=exemption_type_id,
        after={"duty_type_id": str(duty_type_id)},
    )


def unmap_exemption_from_duty_type(
    session: Session,
    *,
    exemption_type_id: uuid.UUID,
    duty_type_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    row = session.get(ExemptionDutyTypeMap, (exemption_type_id, duty_type_id))
    if row is None:
        return  # idempotent
    session.delete(row)
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_map.remove",
        entity_type="exemption_type",
        entity_id=exemption_type_id,
        before={"duty_type_id": str(duty_type_id)},
    )


def list_exemption_duty_type_ids(
    session: Session, *, exemption_type_id: uuid.UUID
) -> list[uuid.UUID]:
    return list(
        session.execute(
            select(ExemptionDutyTypeMap.duty_type_id).where(
                ExemptionDutyTypeMap.exemption_type_id == exemption_type_id
            )
        )
        .scalars()
        .all()
    )


def set_exemption_duty_types(
    session: Session,
    *,
    exemption_type_id: uuid.UUID,
    duty_type_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> None:
    if session.get(ExemptionType, exemption_type_id) is None:
        raise DutyConfigError("exemption_type_not_found")
    desired = set(duty_type_ids)
    for dtid in desired:
        if session.get(DutyType, dtid) is None:
            raise DutyConfigError("duty_type_not_found")
    current = set(list_exemption_duty_type_ids(session, exemption_type_id=exemption_type_id))
    for dtid in desired - current:
        map_exemption_to_duty_type(
            session, exemption_type_id=exemption_type_id, duty_type_id=dtid, actor_id=actor_id
        )
    for dtid in current - desired:
        unmap_exemption_from_duty_type(
            session, exemption_type_id=exemption_type_id, duty_type_id=dtid, actor_id=actor_id
        )
