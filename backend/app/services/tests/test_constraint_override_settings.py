from __future__ import annotations

from app.services.constraint_override_settings import manual_override_allowed
from app.services.settings_loader import set_setting


def test_defaults_to_allowed_when_unset(app_session):
    assert manual_override_allowed(app_session) is True


def test_reads_setting_when_present(app_session):
    set_setting(app_session, "constraints.allow_manual_override", False, actor_id=None)
    assert manual_override_allowed(app_session) is False

    set_setting(app_session, "constraints.allow_manual_override", True, actor_id=None)
    assert manual_override_allowed(app_session) is True
