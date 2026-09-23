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


import secrets

from app.db.models import Soldier, SoldierHrProfile
from app.services.hr.mapping import HeldForReview, MappedSoldierFields, map_hr_user
from app.services.hr.person_sync import _apply_new_person, _mark_held


def _mapped(**overrides: object) -> MappedSoldierFields:
    defaults: dict[str, object] = dict(full_name="ישראל ישראלי", personal_number="ps-new-1")
    defaults.update(overrides)
    return MappedSoldierFields(**defaults)


def test_apply_new_person_creates_soldier_with_placeholder_password(admin_session):
    holding = _holding_node(admin_session)
    user = _hr_user(personal_number="ps-new-1", full_name="ישראל ישראלי")
    mapped = _mapped()

    soldier, profile = _apply_new_person(admin_session, user, mapped)
    admin_session.commit()

    assert soldier.personal_number == "ps-new-1"
    assert soldier.must_change_password is True
    assert soldier.hierarchy_node_id == holding.id
    assert profile.soldier_id == soldier.id
    assert profile.sync_status == "synced"


def test_apply_new_person_links_existing_soldier_without_touching_password(admin_session):
    from tests.helpers import create_soldier

    _holding_node(admin_session)
    existing = create_soldier(admin_session, personal_number="ps-existing-1")
    original_hash = existing.password_hash
    original_role = existing.role

    user = _hr_user(personal_number="ps-existing-1", full_name=existing.full_name)
    mapped = _mapped(personal_number="ps-existing-1", full_name=existing.full_name)

    soldier, profile = _apply_new_person(admin_session, user, mapped)
    admin_session.commit()

    assert soldier.id == existing.id
    assert soldier.password_hash == original_hash
    assert soldier.role == original_role
    assert profile.soldier_id == existing.id


def test_mark_held_creates_profile_without_soldier(admin_session):
    user = _hr_user(personal_number="ps-held-1")
    held = HeldForReview(personal_number="ps-held-1", reasons=["unmappable rank: 'x'"])

    profile = _mark_held(admin_session, user, held)
    admin_session.commit()

    assert profile.soldier_id is None
    assert profile.sync_status == "held_for_review"
    assert "unmappable rank" in profile.review_reason
    assert admin_session.query(Soldier).filter_by(personal_number="ps-held-1").first() is None


def test_mark_held_updates_existing_held_profile_not_duplicate(admin_session):
    user = _hr_user(personal_number="ps-held-2")
    held1 = HeldForReview(personal_number="ps-held-2", reasons=["first reason"])
    held2 = HeldForReview(personal_number="ps-held-2", reasons=["second reason"])

    _mark_held(admin_session, user, held1)
    admin_session.commit()
    _mark_held(admin_session, user, held2)
    admin_session.commit()

    rows = admin_session.query(SoldierHrProfile).filter_by(personal_number="ps-held-2").all()
    assert len(rows) == 1
    assert "second reason" in rows[0].review_reason
