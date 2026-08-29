from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import RangeEvent, RangeLocation


class RangeLocationInUseError(Exception):
    pass


def create_range_location(
    session: Session, *, name: str, actor_id: uuid.UUID | None = None
) -> RangeLocation:
    loc = RangeLocation(name=name)
    session.add(loc)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="range_location.create",
        entity_type="range_location",
        entity_id=loc.id,
        after={"name": name},
    )
    return loc


def usage_count(session: Session, location_id: uuid.UUID) -> int:
    return int(session.scalar(
        select(func.count(RangeEvent.id)).where(RangeEvent.range_location_id == location_id)
    ) or 0)


def update_range_location(
    session: Session, *, location: RangeLocation, name: str | None = None,
    active: bool | None = None, actor_id: uuid.UUID | None = None,
) -> RangeLocation:
    before = {"name": location.name, "active": location.active}
    if name is not None:
        location.name = name.strip()
    if active is not None:
        location.active = active
    write_audit(
        session, actor_id=actor_id, action="range_location.update",
        entity_type="range_location", entity_id=location.id,
        before=before, after={"name": location.name, "active": location.active},
    )
    session.flush()
    return location


def delete_range_location(
    session: Session, *, location: RangeLocation, actor_id: uuid.UUID | None = None,
) -> None:
    if usage_count(session, location.id) > 0:
        raise RangeLocationInUseError("location_in_use")
    write_audit(
        session, actor_id=actor_id, action="range_location.delete",
        entity_type="range_location", entity_id=location.id,
        before={"name": location.name, "active": location.active},
    )
    session.delete(location)
