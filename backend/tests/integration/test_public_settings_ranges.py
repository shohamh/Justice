from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import SystemSetting
from tests.helpers import auth_headers, create_soldier


def test_mitvachim_enabled_appears_in_public_settings(client: TestClient, admin_session: Session) -> None:
    # Ensure mitvachim.enabled exists (should be seeded by migration, but verify it)
    if not admin_session.query(SystemSetting).filter_by(key="mitvachim.enabled").first():
        admin_session.add(SystemSetting(key="mitvachim.enabled", value=True, updated_by=None))
        admin_session.commit()

    soldier = create_soldier(admin_session, personal_number="mitvachim_test_001")
    response = client.get("/api/settings/public", headers=auth_headers(soldier))
    assert response.status_code == 200
    assert "mitvachim.enabled" in response.json()["settings"]


def test_mitvachim_public_value_and_range_route_follow_toggle(client: TestClient, admin_session: Session) -> None:
    soldier = create_soldier(admin_session, personal_number="mitvachim_gate_001")
    setting = admin_session.get(SystemSetting, "mitvachim.enabled")
    if setting is None:
        setting = SystemSetting(key="mitvachim.enabled", value=False, updated_by=None)
        admin_session.add(setting)
    setting.value = False
    admin_session.commit()

    headers = auth_headers(soldier)
    assert client.get("/api/settings/public", headers=headers).json()["settings"]["mitvachim.enabled"] is False
    assert client.get(f"/api/ranges?node_id={soldier.hierarchy_node_id}", headers=headers).status_code == 404

    setting.value = True
    admin_session.commit()
    assert client.get("/api/settings/public", headers=headers).json()["settings"]["mitvachim.enabled"] is True
