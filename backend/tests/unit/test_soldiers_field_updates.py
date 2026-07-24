from __future__ import annotations

import uuid
from datetime import date

from app.services.eligibility import SOLDIER_EDITABLE_FIELDS
from app.services.soldiers import approve_field_update, submit_field_update
from app.db.models import Soldier


def test_mandatory_end_date_and_discharge_date_are_editable():
    assert "mandatory_end_date" in SOLDIER_EDITABLE_FIELDS
    assert "discharge_date" in SOLDIER_EDITABLE_FIELDS


def test_pending_field_update_flags_commander_as_unable_to_approve(client, admin_session):
    """A plain commander (not a duty manager) is shown SOLDIER_READ-scoped
    items today, but the approve endpoint requires SOLDIER_UPDATE, which
    commanders don't have — can_approve must be False so the frontend can
    hide the button instead of showing one that always 403s."""
    from tests.helpers import auth_headers, create_node, create_soldier

    node = create_node(admin_session, level="branch", name="fu_flag_node")
    commander = create_soldier(admin_session, personal_number="fu_flag_cmd", role="commander")
    node.commander_id = commander.id
    soldier = create_soldier(admin_session, personal_number="fu_flag_sol", hierarchy_node_id=node.id)
    admin_session.commit()

    submit_field_update(
        admin_session, soldier_id=soldier.id, field_name="discharge_date", new_value="2027-01-01",
        actor_id=soldier.id,
    )
    admin_session.commit()

    r = client.get("/api/soldiers/field-updates/pending", headers=auth_headers(commander))
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["can_approve"] is False


def test_approve_field_update_writes_mandatory_end_date(admin_session):
    from tests.helpers import create_node

    node = create_node(admin_session, level="unit", name=f"unit_{uuid.uuid4().hex[:8]}")
    soldier = Soldier(
        personal_number=f"pn_{uuid.uuid4().hex[:8]}",
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node.id,
    )
    admin_session.add(soldier)
    admin_session.flush()

    req = submit_field_update(
        admin_session,
        soldier_id=soldier.id,
        field_name="mandatory_end_date",
        new_value="2027-06-01",
        actor_id=soldier.id,
    )
    admin_session.flush()

    approve_field_update(admin_session, update=req, actor_id=soldier.id)

    assert soldier.mandatory_end_date == date(2027, 6, 1)


def test_approve_field_update_writes_discharge_date(admin_session):
    from tests.helpers import create_node

    node = create_node(admin_session, level="unit", name=f"unit_{uuid.uuid4().hex[:8]}")
    soldier = Soldier(
        personal_number=f"pn_{uuid.uuid4().hex[:8]}",
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node.id,
    )
    admin_session.add(soldier)
    admin_session.flush()

    req = submit_field_update(
        admin_session,
        soldier_id=soldier.id,
        field_name="discharge_date",
        new_value="2028-01-15",
        actor_id=soldier.id,
    )
    admin_session.flush()

    approve_field_update(admin_session, update=req, actor_id=soldier.id)

    assert soldier.discharge_date == date(2028, 1, 15)
