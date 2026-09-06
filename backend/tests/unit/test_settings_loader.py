import pytest
from sqlalchemy import text

from app.services.settings_loader import SettingNotFound, SettingsValidationError, get_setting, get_setting_int, set_setting, validate_settings_update


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
    audit = admin_session.execute(
        text(
            "SELECT before, after FROM audit_log WHERE action='system_setting.update' ORDER BY created_at DESC LIMIT 1"
        )
    ).first()
    assert audit is not None
    before, after = audit
    assert before == {"value": 15}
    assert after == {"value": 20}


def test_get_setting_int_returns_value(admin_session):
    assert get_setting_int(admin_session, "auth.session_minutes", 999) == 15


def test_get_setting_int_falls_back_to_default(admin_session):
    assert get_setting_int(admin_session, "does.not.exist", 42) == 42


def test_weapon_qualification_settings_absent_by_default(admin_session):
    for key in ("weapon_qualification.enforce_eligibility", "weapon_qualification.pending_excusal_disqualifies"):
        with pytest.raises(SettingNotFound):
            get_setting(admin_session, key)


def test_weapon_qualification_settings_roundtrip(admin_session):
    set_setting(admin_session, "weapon_qualification.enforce_eligibility", False, actor_id=None)
    admin_session.commit()
    assert get_setting(admin_session, "weapon_qualification.enforce_eligibility") is False


def test_reset_date_overrides_accepts_valid_dict():
    merged = validate_settings_update(
        {}, {"fairness.reset_date_overrides": {"11111111-1111-1111-1111-111111111111": "2026-08-01"}}
    )
    assert merged["fairness.reset_date_overrides"] == {
        "11111111-1111-1111-1111-111111111111": "2026-08-01"
    }


def test_reset_date_overrides_accepts_empty_dict():
    merged = validate_settings_update({}, {"fairness.reset_date_overrides": {}})
    assert merged["fairness.reset_date_overrides"] == {}


def test_reset_date_overrides_rejects_non_dict():
    with pytest.raises(SettingsValidationError) as exc:
        validate_settings_update({}, {"fairness.reset_date_overrides": ["2026-08-01"]})
    assert exc.value.code == "reset_date_overrides_invalid"


def test_reset_date_overrides_rejects_bad_date_value():
    with pytest.raises(SettingsValidationError) as exc:
        validate_settings_update(
            {}, {"fairness.reset_date_overrides": {"11111111-1111-1111-1111-111111111111": "not-a-date"}}
        )
    assert exc.value.code == "reset_date_overrides_invalid"


def test_reset_date_overrides_rejects_non_uuid_key():
    with pytest.raises(SettingsValidationError) as exc:
        validate_settings_update(
            {}, {"fairness.reset_date_overrides": {"not-a-uuid": "2026-08-01"}}
        )
    assert exc.value.code == "reset_date_overrides_invalid"
