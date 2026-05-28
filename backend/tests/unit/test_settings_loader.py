import pytest
from sqlalchemy import text

from app.services.settings_loader import SettingNotFound, get_setting, set_setting


def test_get_known_setting_returns_value(admin_session):
    val = get_setting(admin_session, "auth.session_minutes")
    assert val == 15


def test_get_unknown_setting_raises(admin_session):
    with pytest.raises(SettingNotFound):
        get_setting(admin_session, "does.not.exist")


def test_set_setting_updates_and_writes_audit(admin_session):
    set_setting(admin_session, "auth.session_minutes", 20, actor_id=None)
    admin_session.commit()
    assert get_setting(admin_session, "auth.session_minutes") == 20
    audit = admin_session.execute(text(
        "SELECT before, after FROM audit_log WHERE action='system_setting.update' ORDER BY created_at DESC LIMIT 1"
    )).first()
    assert audit is not None
    before, after = audit
    assert before == {"value": 15}
    assert after == {"value": 20}
