from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.audit.writer import write_audit


def record_sync_divergence(
    session: Session,
    *,
    soldier_hr_profile_id: uuid.UUID,
    field_name: str,
    hr_value: Any,
    local_value: Any,
) -> None:
    """Record that a sync run skipped writing `field_name` because it has
    been locally overridden. Called by the person-sync engine (a later
    subsystem) once per skipped field per sync run — not called anywhere
    in this subsystem yet."""
    write_audit(
        session,
        actor_id=None,
        action="hr_sync.field_skipped_overridden",
        entity_type="soldier_hr_profile",
        entity_id=soldier_hr_profile_id,
        context={"field_name": field_name, "hr_value": hr_value, "local_value": local_value},
    )
