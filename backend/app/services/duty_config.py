from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyLocation,
    DutyType,
    ExemptionDutyLocationMap,
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
    contact_name: str | None = None,
    contact_phone: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    instructions: str | None = None,
    is_external: bool = False,
    requires_weapon: bool = False,
    eligible_node_ids: list[uuid.UUID] | None = None,
    requirements: dict | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyType:
    if score_per_day < 0:
        raise DutyConfigError("score_per_day_must_be_positive")
    if session.execute(select(DutyType.id).where(DutyType.name == name)).first():
        raise DutyConfigError("name_taken")
    if requirements is not None:
        from app.services.eligibility import DutyTypeRequirements
        DutyTypeRequirements.model_validate(requirements)  # validate shape
    dt = DutyType(
        name=name,
        score_per_day=score_per_day,
        description=description,
        reserve_ratio=reserve_ratio,
        reserve_minimum=reserve_minimum,
        contact_name=contact_name,
        contact_phone=contact_phone,
        start_time=start_time,
        end_time=end_time,
        instructions=instructions,
        is_external=is_external,
        requires_weapon=requires_weapon,
        eligible_node_ids=eligible_node_ids,
        **({"requirements": requirements} if requirements is not None else {}),
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
            "is_external": is_external,
            "requires_weapon": requires_weapon,
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
    contact_name: str | None = None,
    contact_phone: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    instructions: str | None = None,
    is_external: bool | None = None,
    requires_weapon: bool | None = None,
    eligible_node_ids: object = ...,
) -> DutyType:
    before = {
        "name": duty_type.name,
        "score_per_day": str(duty_type.score_per_day),
        "description": duty_type.description,
    }
    if score_per_day is not None:
        if score_per_day < 0:
            raise DutyConfigError("score_per_day_must_be_positive")
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
    if contact_name is not None:
        duty_type.contact_name = contact_name
    if contact_phone is not None:
        duty_type.contact_phone = contact_phone
    if start_time is not None:
        duty_type.start_time = start_time
    if end_time is not None:
        duty_type.end_time = end_time
    if instructions is not None:
        duty_type.instructions = instructions
    if is_external is not None:
        duty_type.is_external = is_external
    if requires_weapon is not None:
        duty_type.requires_weapon = requires_weapon
    if eligible_node_ids is not ...:
        duty_type.eligible_node_ids = eligible_node_ids  # type: ignore[assignment]  # None means clear
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
            "requires_weapon": duty_type.requires_weapon,
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
    is_commander_exemption: bool = False,
    forbids_weapons: bool = False,
    actor_id: uuid.UUID | None = None,
) -> ExemptionType:
    if session.execute(select(ExemptionType.id).where(ExemptionType.name == name)).first():
        raise DutyConfigError("name_taken")
    et = ExemptionType(
        name=name,
        description=description,
        is_global=is_global,
        is_medical=is_medical,
        is_commander_exemption=is_commander_exemption,
        forbids_weapons=forbids_weapons,
    )
    session.add(et)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_type.create",
        entity_type="exemption_type",
        entity_id=et.id,
        after={
            "name": name,
            "is_global": is_global,
            "is_medical": is_medical,
            "is_commander_exemption": is_commander_exemption,
            "forbids_weapons": forbids_weapons,
        },
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
    is_commander_exemption: bool | None = None,
    forbids_weapons: bool | None = None,
    active: bool | None = None,
    actor_id: uuid.UUID | None = None,
) -> ExemptionType:
    before = {
        "name": exemption_type.name,
        "description": exemption_type.description,
        "is_global": exemption_type.is_global,
        "is_medical": exemption_type.is_medical,
        "is_commander_exemption": exemption_type.is_commander_exemption,
        "forbids_weapons": exemption_type.forbids_weapons,
        "active": exemption_type.active,
    }
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
    if is_commander_exemption is not None:
        exemption_type.is_commander_exemption = is_commander_exemption
    if forbids_weapons is not None:
        exemption_type.forbids_weapons = forbids_weapons
    if active is not None:
        exemption_type.active = active
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_type.update",
        entity_type="exemption_type",
        entity_id=exemption_type.id,
        before=before,
        after={
            "name": exemption_type.name,
            "description": exemption_type.description,
            "is_global": exemption_type.is_global,
            "is_medical": exemption_type.is_medical,
            "is_commander_exemption": exemption_type.is_commander_exemption,
            "forbids_weapons": exemption_type.forbids_weapons,
            "active": exemption_type.active,
        },
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


def disable_exemption_type_and_revoke_all(
    session: Session, *, exemption_type: ExemptionType, reason: str, actor_id: uuid.UUID
) -> int:
    """Deactivate exemption_type and revoke every soldier's currently-active,
    not-already-revoked exemption of this type, using the shared reason."""
    from app.services.exemptions import revoke_exemption

    today = date.today()
    active_exemption_ids = session.execute(
        select(SoldierExemption.id).where(
            SoldierExemption.exemption_type_id == exemption_type.id,
            SoldierExemption.revoked_at.is_(None),
            or_(SoldierExemption.end_date.is_(None), SoldierExemption.end_date >= today),
        )
    ).scalars().all()

    exemption_type.active = False
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_type.disable",
        entity_type="exemption_type",
        entity_id=exemption_type.id,
        before={"active": True},
        after={"active": False},
        context={"reason": reason},
    )

    revoked_count = 0
    for exemption_id in active_exemption_ids:
        revoke_exemption(session, exemption_id=exemption_id, reason=reason, actor_id=actor_id)
        revoked_count += 1
    return revoked_count


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


def map_exemption_to_duty_location(
    session: Session,
    *,
    exemption_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    if session.get(ExemptionType, exemption_type_id) is None:
        raise DutyConfigError("exemption_type_not_found")
    if session.get(DutyLocation, duty_location_id) is None:
        raise DutyConfigError("duty_location_not_found")
    exists = session.get(ExemptionDutyLocationMap, (exemption_type_id, duty_location_id))
    if exists is not None:
        return  # idempotent
    session.add(
        ExemptionDutyLocationMap(exemption_type_id=exemption_type_id, duty_location_id=duty_location_id)
    )
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_location_map.add",
        entity_type="exemption_type",
        entity_id=exemption_type_id,
        after={"duty_location_id": str(duty_location_id)},
    )


def unmap_exemption_from_duty_location(
    session: Session,
    *,
    exemption_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    row = session.get(ExemptionDutyLocationMap, (exemption_type_id, duty_location_id))
    if row is None:
        return  # idempotent
    session.delete(row)
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption_location_map.remove",
        entity_type="exemption_type",
        entity_id=exemption_type_id,
        before={"duty_location_id": str(duty_location_id)},
    )


def list_exemption_duty_location_ids(
    session: Session, *, exemption_type_id: uuid.UUID
) -> list[uuid.UUID]:
    return list(
        session.execute(
            select(ExemptionDutyLocationMap.duty_location_id).where(
                ExemptionDutyLocationMap.exemption_type_id == exemption_type_id
            )
        )
        .scalars()
        .all()
    )


def set_exemption_duty_locations(
    session: Session,
    *,
    exemption_type_id: uuid.UUID,
    duty_location_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> None:
    if session.get(ExemptionType, exemption_type_id) is None:
        raise DutyConfigError("exemption_type_not_found")
    desired = set(duty_location_ids)
    for lid in desired:
        if session.get(DutyLocation, lid) is None:
            raise DutyConfigError("duty_location_not_found")
    current = set(list_exemption_duty_location_ids(session, exemption_type_id=exemption_type_id))
    for lid in desired - current:
        map_exemption_to_duty_location(
            session, exemption_type_id=exemption_type_id, duty_location_id=lid, actor_id=actor_id
        )
    for lid in current - desired:
        unmap_exemption_from_duty_location(
            session, exemption_type_id=exemption_type_id, duty_location_id=lid, actor_id=actor_id
        )
