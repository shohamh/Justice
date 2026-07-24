from __future__ import annotations

import uuid

from app.db.models import DutyManagerScope
from app.services.approval_scope import (
    commander_chain_for_soldier,
    duty_manager_chain_for_soldier,
    nearest_commander_for_soldier,
    nearest_duty_manager_for_soldier,
)
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_duty_manager_chain_empty_when_no_scope_assigned(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()

    assert duty_manager_chain_for_soldier(admin_session, soldier.id) == []
    assert nearest_duty_manager_for_soldier(admin_session, soldier.id) is None


def test_duty_manager_chain_includes_scope_holder_of_soldiers_own_node(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()

    chain = duty_manager_chain_for_soldier(admin_session, soldier.id)
    assert chain == [dm.id]
    assert nearest_duty_manager_for_soldier(admin_session, soldier.id) == dm.id


def test_duty_manager_chain_walks_to_root_nearest_first(admin_session):
    root = create_node(admin_session, level="branch", name=f"root_{_uid()}")
    child = create_node(admin_session, level="unit", name=f"child_{_uid()}", parent=root)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=child.id)
    near_dm = create_soldier(admin_session, personal_number=f"near_{_uid()}", role="duty_manager")
    far_dm = create_soldier(admin_session, personal_number=f"far_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=near_dm.id, hierarchy_node_id=child.id))
    admin_session.add(DutyManagerScope(duty_manager_id=far_dm.id, hierarchy_node_id=root.id))
    admin_session.commit()

    chain = duty_manager_chain_for_soldier(admin_session, soldier.id)
    assert chain == [near_dm.id, far_dm.id]


def test_duty_manager_chain_does_not_leak_out_of_scope_managers(admin_session):
    in_node = create_node(admin_session, level="unit", name=f"in_{_uid()}")
    out_node = create_node(admin_session, level="unit", name=f"out_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=in_node.id)
    out_dm = create_soldier(admin_session, personal_number=f"out_dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=out_dm.id, hierarchy_node_id=out_node.id))
    admin_session.commit()

    assert duty_manager_chain_for_soldier(admin_session, soldier.id) == []


def test_commander_chain_still_importable_from_new_module(admin_session):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}")
    commander = create_soldier(admin_session, personal_number=f"c_{_uid()}")
    node.commander_id = commander.id
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    admin_session.commit()

    assert commander_chain_for_soldier(admin_session, soldier.id) == [commander.id]
    assert nearest_commander_for_soldier(admin_session, soldier.id) == commander.id
