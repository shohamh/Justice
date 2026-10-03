from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def write_audit(
    session: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit row atomically with a mutation."""
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        context=context,
    )
    session.add(entry)
    return entry


def write_file_download_audit(
    session: Session,
    *,
    actor_id: uuid.UUID | None,
    allowed: bool,
    resource_id: uuid.UUID | None,
    file_class: str | None,
    request_id: str,
) -> AuditLog:
    """Write a privacy-safe decision record; never pass file metadata here."""
    return write_audit(
        session,
        actor_id=actor_id,
        action="file.download.allow" if allowed else "file.download.deny",
        entity_type="file",
        entity_id=resource_id,
        context={"file_class": file_class, "request_id": request_id},
    )
