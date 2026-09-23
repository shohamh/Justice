from __future__ import annotations

import uuid

from app.db.models import HierarchyNode, HrHierarchyNodeMap
from app.services.hr.person_sync import resolve_placement_node_id
from app.services.hr.schemas import HrUser
from app.services.settings_loader import set_setting


def _hr_user(**overrides: object) -> HrUser:
    defaults: dict[str, object] = dict(
        full_name="ישראל ישראלי", personal_number="ps-1",
        team_id=None, mador_id=None, branch_id=None,
        department_id=None, shetach_id=None, unit_id=None,
    )
    defaults.update(overrides)
    return HrUser(**defaults)


def _node(session, name: str) -> HierarchyNode:
    node = HierarchyNode(level="unit", name=name, parent_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.commit()
    return node


def _holding_node(session) -> HierarchyNode:
    node = _node(session, "Holding")
    set_setting(session, "system.holding_node_id", str(node.id), actor_id=None)
    session.commit()
    return node


def test_resolve_placement_prefers_team_id_over_others(admin_session):
    team_node = _node(admin_session, "Team Node")
    mador_node = _node(admin_session, "Mador Node")
    admin_session.add_all([
        HrHierarchyNodeMap(hr_group_id="team-1", node_id=team_node.id),
        HrHierarchyNodeMap(hr_group_id="mador-1", node_id=mador_node.id),
    ])
    admin_session.commit()

    user = _hr_user(team_id="team-1", mador_id="mador-1")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == team_node.id


def test_resolve_placement_falls_back_through_priority_order(admin_session):
    branch_node = _node(admin_session, "Branch Node")
    admin_session.add(HrHierarchyNodeMap(hr_group_id="branch-1", node_id=branch_node.id))
    admin_session.commit()

    # team_id and mador_id present but unresolved; branch_id resolves.
    user = _hr_user(team_id="team-unresolved", mador_id="mador-unresolved", branch_id="branch-1")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == branch_node.id


def test_resolve_placement_no_ids_present_uses_holding_node(admin_session):
    holding = _holding_node(admin_session)

    user = _hr_user()
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == holding.id


def test_resolve_placement_unresolved_ids_use_holding_node(admin_session):
    holding = _holding_node(admin_session)

    user = _hr_user(team_id="nonexistent", unit_id="also-nonexistent")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == holding.id
