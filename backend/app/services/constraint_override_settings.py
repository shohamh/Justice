from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.settings_loader import SettingNotFound, get_setting

MANUAL_OVERRIDE_KEY = "constraints.allow_manual_override"


def manual_override_allowed(session: Session) -> bool:
    """True unless an admin has explicitly turned off manual overriding of
    approved personal constraints during duty/range manual assignment."""
    try:
        return bool(get_setting(session, MANUAL_OVERRIDE_KEY))
    except SettingNotFound:
        return True
