from __future__ import annotations

import uuid
from datetime import date

from dateutil.relativedelta import relativedelta

from app.services.eligibility import SOLDIER_EDITABLE_FIELDS
from app.services.rank_advancement import upsert_interval
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


def test_junior_duty_manager_cannot_approve_rank_field_update(client, admin_session):
    from tests.helpers import auth_headers, create_node, create_soldier

    node = create_node(admin_session, level="branch", name="fu_rank_junior")
    duty_manager = create_soldier(
        admin_session, personal_number="fu_rank_junior_dm", role="duty_manager", hierarchy_node_id=node.id,
    )
    soldier = create_soldier(
        admin_session, personal_number="fu_rank_junior_soldier", hierarchy_node_id=node.id,
    )
    admin_session.commit()
    submitted = client.post(
        f"/api/soldiers/{soldier.id}/field-updates",
        json={"field_name": "rank", "new_value": "סמר"},
        headers=auth_headers(soldier),
    )

    response = client.post(
        f"/api/soldiers/{soldier.id}/field-updates/{submitted.json()['id']}/approve",
        json={}, headers=auth_headers(duty_manager),
    )

    assert response.status_code == 403


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


def test_approve_field_update_rank_initializes_next_rank_date(admin_session):
    """Task 13: approve_field_update()'s `elif field == "rank":` branch is one
    of the writers of Soldier.rank — it must initialize next_rank_date the
    same way update_soldier_profile does."""
    from tests.helpers import create_node

    node = create_node(admin_session, level="unit", name=f"unit_{uuid.uuid4().hex[:8]}")
    soldier = Soldier(
        personal_number=f"pn_{uuid.uuid4().hex[:8]}",
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node.id,
        rank="טוראי",
        enlistment_date=date(2021, 1, 15),
    )
    admin_session.add(soldier)
    admin_session.flush()
    req = submit_field_update(
        admin_session,
        soldier_id=soldier.id,
        field_name="rank",
        new_value="סמר",
        actor_id=soldier.id,
    )
    admin_session.flush()

    approve_field_update(admin_session, update=req, actor_id=soldier.id)

    assert soldier.rank == "סמר"
    assert soldier.current_rank_since == date(2021, 1, 15)
    assert soldier.next_rank_date == date(2025, 9, 15)
    assert soldier.next_rank_date_overridden is False


def test_approve_field_update_rank_without_interval_leaves_next_rank_date_none(admin_session):
    from tests.helpers import create_node

    node = create_node(admin_session, level="unit", name=f"unit_{uuid.uuid4().hex[:8]}")
    soldier = Soldier(
        personal_number=f"pn_{uuid.uuid4().hex[:8]}",
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node.id,
        rank="טוראי",
    )
    admin_session.add(soldier)
    upsert_interval(
        admin_session, track="enlisted", rank="רבט", months_to_next=None,
        advance_on_career_entry=False, actor_id=None,
    )
    admin_session.flush()

    req = submit_field_update(
        admin_session,
        soldier_id=soldier.id,
        field_name="rank",
        new_value="רבט",
        actor_id=soldier.id,
    )
    admin_session.flush()

    approve_field_update(admin_session, update=req, actor_id=soldier.id)

    assert soldier.rank == "רבט"
    assert soldier.next_rank_date is None
    assert soldier.next_rank_date_overridden is False
