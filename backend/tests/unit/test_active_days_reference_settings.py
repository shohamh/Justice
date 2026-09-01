from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import inspect

from app.db.models import AuditLog, HierarchyNode, Soldier, SystemSetting
from app.services.invite_codes import create_invite_code
from tests.helpers import auth_headers, create_node, create_soldier

REFERENCE_DATE_KEY = "scoring.active_days_reference_date"


def _setup_holding(session) -> HierarchyNode:
    holding = HierarchyNode(level="division", name=f"holding-{uuid.uuid4().hex}", path_ids=[])
    session.add(holding)
    session.flush()
    holding.path_ids = [holding.id]
    session.add(SystemSetting(key="system.holding_node_id", value=str(holding.id), updated_by=None))
    session.commit()
    return holding


def _registration_payload(invite_code: str, node_id: uuid.UUID) -> dict[str, object]:
    return {
        "invite_code": invite_code,
        "personal_number": str(uuid.uuid4().int % 90_000_000 + 10_000_000),
        "full_name": "Test Soldier",
        "password": "secure-password-1",
        "phone": "050-1234567",
        "email": "soldier@example.com",
        "gender": "male",
        "is_officer": False,
        "rank": "טוראי",
        "enlistment_date": (date.today() - timedelta(days=600)).isoformat(),
        "unit_join_date": (date.today() - timedelta(days=590)).isoformat(),
        "mandatory_end_date": (date.today() + timedelta(days=200)).isoformat(),
        "discharge_date": (date.today() + timedelta(days=600)).isoformat(),
        "last_mitvahim_date": (date.today() - timedelta(days=30)).isoformat(),
        "last_alal_date": None,
        "requested_node_id": str(node_id),
        "exemption_requests": [],
        "personal_constraints": [],
    }


def _register(client, payload: dict[str, object]):
    return client.post("/api/auth/register", data={"payload": json.dumps(payload)})


def test_soldier_unit_join_date_and_migration_are_nullable():
    column = inspect(Soldier).columns["unit_join_date"]
    assert column.nullable is True

    migration = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "20260901_active_days_reference_date.py"
    )
    assert migration.exists()
    assert 'sa.Column("unit_join_date", sa.Date(), nullable=True)' in migration.read_text(encoding="utf-8")


def test_admin_round_trip_audits_active_days_reference_date(client, admin_session):
    admin = create_soldier(admin_session, personal_number="active-days-admin", role="admin")
    reference_date = (date.today() - timedelta(days=5)).isoformat()

    response = client.put(
        "/api/admin/system-settings",
        json={"settings": {REFERENCE_DATE_KEY: reference_date}},
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["settings"][REFERENCE_DATE_KEY] == reference_date
    audit = admin_session.query(AuditLog).filter_by(action="system_setting.update").one()
    assert audit.context == {"key": REFERENCE_DATE_KEY}
    assert audit.after == {"value": reference_date}


def test_admin_cannot_set_active_days_reference_date_in_the_future(client, admin_session):
    admin = create_soldier(admin_session, personal_number="active-days-future", role="admin")

    response = client.put(
        "/api/admin/system-settings",
        json={"settings": {REFERENCE_DATE_KEY: (date.today() + timedelta(days=1)).isoformat()}},
        headers=auth_headers(admin),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "active_days_reference_date_in_future"


def test_first_registration_initializes_absent_active_days_reference_date(client, admin_session):
    holding = _setup_holding(admin_session)
    requested_node = create_node(admin_session, level="unit", name="unit", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    response = _register(client, _registration_payload(invite.code, requested_node.id))

    assert response.status_code == 200, response.text
    assert admin_session.get(SystemSetting, REFERENCE_DATE_KEY).value == date.today().isoformat()


def test_registration_preserves_existing_active_days_reference_date(client, admin_session):
    holding = _setup_holding(admin_session)
    requested_node = create_node(admin_session, level="unit", name="unit", parent=holding)
    existing_date = (date.today() - timedelta(days=90)).isoformat()
    admin_session.add(SystemSetting(key=REFERENCE_DATE_KEY, value=existing_date, updated_by=None))
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    response = _register(client, _registration_payload(invite.code, requested_node.id))

    assert response.status_code == 200, response.text
    assert admin_session.get(SystemSetting, REFERENCE_DATE_KEY).value == existing_date
