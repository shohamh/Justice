from __future__ import annotations

import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_hakpaza_routes_403_when_disabled(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number=f"hk_{_uid()}", role="admin")
    set_setting(admin_session, "forced_callup.enabled", False, actor_id=admin.id)
    admin_session.commit()

    r = client.get("/api/hakpaza/pending-count", headers=auth_headers(admin))
    assert r.status_code == 403
    assert r.json()["detail"] == "hakpaza_disabled"


def test_hakpaza_routes_enabled_by_default(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number=f"hk2_{_uid()}", role="admin")
    r = client.get("/api/hakpaza/pending-count", headers=auth_headers(admin))
    assert r.status_code == 200
