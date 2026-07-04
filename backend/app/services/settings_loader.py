from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import SystemSetting


class SettingNotFound(KeyError):
    """Raised when a system_settings key is not present."""


def _json_safe(value: Any) -> Any:
    # why: the value column is JSON; Decimal isn't JSON-serializable, so store it
    # as a string and rely on callers parsing it back (e.g. Decimal(str(...))).
    if isinstance(value, Decimal):
        return str(value)
    return value


def get_setting(session: Session, key: str) -> Any:
    row = session.get(SystemSetting, key)
    if row is None:
        raise SettingNotFound(key)
    return row.value


def get_setting_int(session: Session, key: str, default: int) -> int:
    try:
        return int(get_setting(session, key))
    except SettingNotFound:
        return default


def set_setting(session: Session, key: str, value: Any, *, actor_id: uuid.UUID | None) -> None:
    value = _json_safe(value)
    row = session.get(SystemSetting, key)
    before = row.value if row is not None else None
    if row is None:
        row = SystemSetting(key=key, value=value, updated_by=actor_id)
        session.add(row)
    else:
        row.value = value
        row.updated_by = actor_id
    write_audit(
        session,
        actor_id=actor_id,
        action="system_setting.update",
        entity_type="system_setting",
        entity_id=None,
        before=None if before is None else {"value": before},
        after={"value": value},
        context={"key": key},
    )
