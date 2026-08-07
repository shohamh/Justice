from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import RangeLocation


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
