from __future__ import annotations

import pytest

from app.db.models import SystemSetting
from app.settings import get_settings
from tests.helpers import auth_headers, create_soldier


def test_telegram_enabled_exposed_via_public_settings(client, admin_session):
    admin_session.add(SystemSetting(key="telegram.enabled", value=False, updated_by=None))
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="PUBSET1")

    resp = client.get("/api/settings/public", headers=auth_headers(soldier))
    assert resp.status_code == 200
    assert resp.json()["settings"]["telegram.enabled"] is False


def test_registration_public_settings_no_auth_required(client, admin_session):
    admin_session.add(SystemSetting(key="registration.email_domain_hint", value="gmail.com", updated_by=None))
    admin_session.add(
        SystemSetting(
            key="fairness.reset_date",
            value="2026-08-31",
            updated_by=None,
        )
    )
    admin_session.commit()

    resp = client.get("/api/settings/public/registration")
    assert resp.status_code == 200
    assert resp.json()["email_domain_hint"] == "gmail.com"
    assert resp.json()["active_days_reference_date"] == "2026-08-31"


def test_registration_public_settings_defaults_to_none(client):
    resp = client.get("/api/settings/public/registration")
    assert resp.status_code == 200
    assert resp.json()["email_domain_hint"] is None
    assert resp.json()["active_days_reference_date"] is None


@pytest.fixture
def loki_env(monkeypatch):
    def _set(value: str | None):
        if value is None:
            monkeypatch.delenv("LOKI_URL", raising=False)
        else:
            monkeypatch.setenv("LOKI_URL", value)
        get_settings.cache_clear()

    yield _set
    monkeypatch.delenv("LOKI_URL", raising=False)
    get_settings.cache_clear()


def test_error_log_source_flag_is_false_when_loki_is_unset(client, admin_session, loki_env):
    loki_env(None)
    soldier = create_soldier(admin_session, personal_number="PUBSET2")

    resp = client.get("/api/settings/public", headers=auth_headers(soldier))

    assert resp.status_code == 200
    assert resp.json()["settings"]["errors.log_source_configured"] is False


def test_error_log_source_flag_is_true_when_loki_is_set(client, admin_session, loki_env):
    loki_env("http://loki.test:3100")
    soldier = create_soldier(admin_session, personal_number="PUBSET3")

    resp = client.get("/api/settings/public", headers=auth_headers(soldier))

    assert resp.json()["settings"]["errors.log_source_configured"] is True
