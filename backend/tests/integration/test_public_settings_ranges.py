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
