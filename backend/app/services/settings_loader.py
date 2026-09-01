from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import SystemSetting


class SettingNotFound(KeyError):
    """Raised when a system_settings key is not present."""


class SettingsValidationError(ValueError):
    """Raised when a proposed settings update fails cross-field validation
    (density t/r ordering, relax-ceiling ordering). `code` is the same
    machine-readable string previously raised as an HTTP 400 `detail`
    (e.g. "t_exceeds_r", "relax_ceiling_invalid")."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# Keys that the UI/Excel import should never expose or allow editing
# (internal/read-only). Canonical location — routes/config_export.py import
# this rather than redefining it.
_HIDDEN_KEYS = {"system.holding_node_id"}
ACTIVE_DAYS_REFERENCE_DATE_KEY = "scoring.active_days_reference_date"

_DENSITY_DEFAULTS = {
    "algorithm.max_duties_per_window": 8,
    "algorithm.max_total_duties_per_window": 15,
    "algorithm.window_t": 14,
    "algorithm.window_r": 28,
    "algorithm.batch_window_days": 28,
    "algorithm.relax_t_ceiling": 10,
    "algorithm.relax_r_ceiling": 20,
}


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


def validate_settings_update(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Pure validation, no DB writes. Merges `updates` onto `current`, applies
    the telegram cascade to the merged view, then re-runs the same t/r density
    and relax-ceiling checks the settings route has always enforced. Raises
    SettingsValidationError on violation; otherwise returns the merged dict."""
    merged = {**current, **updates}

    if merged.get("telegram.enabled") is False:
        merged["registration.telegram_required"] = False

    if ACTIVE_DAYS_REFERENCE_DATE_KEY in updates:
        reference_date = updates[ACTIVE_DAYS_REFERENCE_DATE_KEY]
        if not isinstance(reference_date, str):
            raise SettingsValidationError("active_days_reference_date_invalid")
        try:
            parsed_reference_date = date.fromisoformat(reference_date)
        except ValueError as exc:
            raise SettingsValidationError("active_days_reference_date_invalid") from exc
        if parsed_reference_date > date.today():
            raise SettingsValidationError("active_days_reference_date_in_future")

    def _density(key: str) -> int:
        return int(merged.get(key, _DENSITY_DEFAULTS[key]))

    t = _density("algorithm.max_duties_per_window")
    r = _density("algorithm.max_total_duties_per_window")
    t_ceil = _density("algorithm.relax_t_ceiling")
    r_ceil = _density("algorithm.relax_r_ceiling")

    if t > r:
        raise SettingsValidationError("t_exceeds_r")
    if t_ceil > r_ceil or t > t_ceil or r > r_ceil:
        raise SettingsValidationError("relax_ceiling_invalid")

    return merged


def initialize_active_days_reference_date(session: Session, registration_date: date) -> None:
    """Set the shared reference date exactly once, without overwriting an admin value."""
    session.execute(
        insert(SystemSetting)
        .values(
            key=ACTIVE_DAYS_REFERENCE_DATE_KEY,
            value=registration_date.isoformat(),
            updated_by=None,
        )
        .on_conflict_do_nothing(index_elements=[SystemSetting.key])
    )


_WEAPON_ENFORCE_KEY = "weapon_qualification.enforce_eligibility"


def weapon_enforcement_changed(current: dict[str, Any], updates: dict[str, Any]) -> bool:
    """True iff `updates` actually flips weapon_qualification.enforce_eligibility
    relative to `current` (key present in the update AND its value differs).
    Pure/no DB access — callers use this to decide whether to trigger a
    weapon-ineligibility recheck. Kept here (rather than duplicated in the
    settings route) since it's the same key `apply_settings` writes."""
    return (
        _WEAPON_ENFORCE_KEY in updates
        and current.get(_WEAPON_ENFORCE_KEY) != updates[_WEAPON_ENFORCE_KEY]
    )


def apply_settings(
    session: Session, current: dict[str, Any], updates: dict[str, Any], *, actor_id: uuid.UUID | None
) -> dict[str, Any]:
    """Validates `updates` against `current` (raises SettingsValidationError on
    failure), then writes each non-hidden key via set_setting — including the
    telegram cascade's forced registration.telegram_required=False, so that
    write actually lands even though it wasn't in the caller's `updates`.

    Note: this function does NOT commit — the caller (system_settings route)
    commits, so the weapon-eligibility-recheck trigger for a
    weapon_qualification.enforce_eligibility change lives in that route
    (after its commit), not here, to run against durable data. See
    weapon_enforcement_changed()."""
    merged = validate_settings_update(current, updates)

    to_write = dict(updates)
    if merged.get("telegram.enabled") is False:
        to_write["registration.telegram_required"] = False

    for key, value in to_write.items():
        if key in _HIDDEN_KEYS:
            continue
        set_setting(session, key=key, value=value, actor_id=actor_id)

    return merged
