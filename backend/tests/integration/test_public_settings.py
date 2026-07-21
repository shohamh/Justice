from __future__ import annotations

from app.db.models import SystemSetting
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
    admin_session.commit()

    resp = client.get("/api/settings/public/registration")
    assert resp.status_code == 200
    assert resp.json()["email_domain_hint"] == "gmail.com"


def test_registration_public_settings_defaults_to_none(client):
    resp = client.get("/api/settings/public/registration")
    assert resp.status_code == 200
    assert resp.json()["email_domain_hint"] is None
