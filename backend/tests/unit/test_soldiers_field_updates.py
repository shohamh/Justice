from __future__ import annotations

import uuid
from datetime import date

from app.services.eligibility import SOLDIER_EDITABLE_FIELDS
from app.services.soldiers import approve_field_update, submit_field_update
from app.db.models import Soldier


def test_mandatory_end_date_and_discharge_date_are_editable():
    assert "mandatory_end_date" in SOLDIER_EDITABLE_FIELDS
    assert "discharge_date" in SOLDIER_EDITABLE_FIELDS


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
