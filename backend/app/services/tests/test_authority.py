# backend/app/services/tests/test_authority.py
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from app.db.models import DutyManagerScope, HierarchyLevelType, HierarchyNode, Soldier
from app.services.authority import (
    RankAdvancementEditScope,
    can_view_soldier_scope,
    commander_can_grant_commander_exemption,
    commander_delete_soldier_authorized,
    dm_scope_covers_level,
    has_any_commander_delete_scope,
    has_any_visibility,
    rank_advancement_edit_authorized,
)


@pytest.fixture(autouse=True)
def _clear_seeded_level_types(app_session):
    """The shared app_session fixture pre-seeds hierarchy_level_types with default
    English-keyed rows (see tests/conftest.py _LEVEL_TYPE_DEFAULTS). This module's
    tests define their own Hebrew-keyed levels/ranks, so clear the defaults first
    to avoid unique-key/unique-rank collisions."""
    app_session.execute(delete(HierarchyLevelType))
    app_session.flush()


def _level(session, key, rank):
    lt = HierarchyLevelType(key=key, label=key, rank=rank)
    session.add(lt)
    session.flush()
    return lt


def test_commander_without_mador_command_cannot_grant_regardless_of_rank(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "פלוגה", 2)
    _level(app_session, "מדור", 3)
    node = HierarchyNode(level="פלוגה", name="Co", path_ids=[])
    app_session.add(node)
    app_session.flush()
    node.path_ids = [node.id]
    s = Soldier(personal_number="1", full_name="X", password_hash="x", rank="אלוף")
    app_session.add(s)
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=s.id) is False


def test_commander_of_mador_or_above_can_grant_regardless_of_rank(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מדור", 2)
    _level(app_session, "כיתה", 3)
    node = HierarchyNode(level="מדור", name="Sector", path_ids=[])
    app_session.add(node)
    app_session.flush()
    node.path_ids = [node.id]
    s = Soldier(personal_number="3", full_name="X", password_hash="x", rank="סמל")
    app_session.add(s)
    app_session.flush()
    node.commander_id = s.id
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=s.id) is True


def test_dm_scope_covers_level_true_when_scope_node_at_or_above_target_level(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "פלוגה", 3)
    scope_node = HierarchyNode(level="מרכז", name="Center", path_ids=[])
    app_session.add(scope_node)
    app_session.flush()
    scope_node.path_ids = [scope_node.id]
    app_session.flush()
    assert dm_scope_covers_level(app_session, scope_node=scope_node, required_level_key="מרכז") is True


def test_commander_exemption_min_level_configurable(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "גדוד", 1)
    _level(app_session, "מדור", 2)
    _level(app_session, "צוות", 3)
    team_node = HierarchyNode(level="צוות", name="Team", path_ids=[])
    app_session.add(team_node)
    app_session.flush()
    team_node.path_ids = [team_node.id]
    cmd = Soldier(personal_number="4", full_name="X", password_hash="x", role="commander")
    app_session.add(cmd)
    app_session.flush()
    team_node.commander_id = cmd.id
    app_session.flush()

    # Default threshold ("מדור") — a צוות commander should NOT qualify.
    assert commander_can_grant_commander_exemption(app_session, commander_id=cmd.id) is False

    # Lower the required threshold to "צוות" via setting — now they should qualify.
    set_setting(app_session, "exemptions.commander_exemption_min_level", "צוות", actor_id=None)
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=cmd.id) is True


def test_dm_scope_covers_level_false_when_scope_node_below_target_level(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "פלוגה", 3)
    scope_node = HierarchyNode(level="פלוגה", name="Co", path_ids=[])
    app_session.add(scope_node)
    app_session.flush()
    scope_node.path_ids = [scope_node.id]
    app_session.flush()
    assert dm_scope_covers_level(app_session, scope_node=scope_node, required_level_key="מרכז") is False


# Tests for can_view_soldier_scope and has_any_visibility


def _node(session, level, name="N", commander_id=None):
    n = HierarchyNode(level=level, name=name, path_ids=[], commander_id=commander_id)
    session.add(n)
    session.flush()
    n.path_ids = [n.id]
    session.flush()
    return n


def _child(session, parent, level, name="Child"):
    n = HierarchyNode(level=level, name=name, parent_id=parent.id, path_ids=[])
    session.add(n)
    session.flush()
    n.path_ids = [*parent.path_ids, n.id]
    session.flush()
    return n


def _soldier(session, personal_number, role="soldier"):
    s = Soldier(personal_number=personal_number, full_name="X", password_hash="x", role=role)
    session.add(s)
    session.flush()
    return s


@pytest.mark.parametrize(
    ("role", "root_level", "expected_inside"),
    [
        ("commander", "מדור", True),
        ("commander", "אגף", True),
        ("commander", "ענף", False),
        ("duty_manager", "מדור", True),
        ("duty_manager", "אגף", True),
        ("duty_manager", "ענף", False),
    ],
)
def test_rank_advancement_authority_requires_senior_in_scope_root(
    app_session, role, root_level, expected_inside,
):
    _level(app_session, "אגף", 1)
    _level(app_session, "מדור", 2)
    _level(app_session, "ענף", 3)
    actor = _soldier(app_session, f"rank_{role}_{root_level}", role=role)
    root = _node(app_session, root_level, name="Root")
    inside = _child(app_session, root, "ענף", name="Inside")
    outside = _node(app_session, "ענף", name="Outside")
    if role == "commander":
        root.commander_id = actor.id
    else:
        app_session.add(DutyManagerScope(duty_manager_id=actor.id, hierarchy_node_id=root.id))
    app_session.flush()

    assert rank_advancement_edit_authorized(app_session, user=actor, target_node=inside) is expected_inside
    assert rank_advancement_edit_authorized(app_session, user=actor, target_node=outside) is False


@pytest.mark.parametrize(
    ("role", "root_level", "expected_inside"),
    [
        ("commander", "מדור", True),
        ("commander", "אגף", True),
        ("commander", "ענף", False),
        ("duty_manager", "מדור", True),
        ("duty_manager", "אגף", True),
        ("duty_manager", "ענף", False),
    ],
)
def test_rank_advancement_edit_scope_matches_per_call_authorization(
    app_session, role, root_level, expected_inside,
):
    """RankAdvancementEditScope (finding 3's hoisted-per-request context) must
    agree with rank_advancement_edit_authorized's per-call result exactly —
    it's a caching layer, not a behavior change."""
    _level(app_session, "אגף", 1)
    _level(app_session, "מדור", 2)
    _level(app_session, "ענף", 3)
    actor = _soldier(app_session, f"rank_scope_{role}_{root_level}", role=role)
    root = _node(app_session, root_level, name="Root")
    inside = _child(app_session, root, "ענף", name="Inside")
    outside = _node(app_session, "ענף", name="Outside")
    if role == "commander":
        root.commander_id = actor.id
    else:
        app_session.add(DutyManagerScope(duty_manager_id=actor.id, hierarchy_node_id=root.id))
    app_session.flush()

    scope = RankAdvancementEditScope(app_session, user=actor)

    assert scope.authorized(inside) is expected_inside
    assert scope.authorized(outside) is False


def test_rank_advancement_edit_scope_admin_bypasses_scope_checks(app_session):
    _level(app_session, "מדור", 1)
    target = _node(app_session, "מדור")
    admin = _soldier(app_session, "rank_scope_admin", role="admin")

    scope = RankAdvancementEditScope(app_session, user=admin)

    assert scope.authorized(target) is True
    assert scope.authorized(None) is True


def test_rank_advancement_edit_scope_none_target_node(app_session):
    _level(app_session, "מדור", 1)
    commander = _soldier(app_session, "rank_scope_none_target", role="commander")
    _node(app_session, "מדור", commander_id=commander.id)

    scope = RankAdvancementEditScope(app_session, user=commander)

    assert scope.authorized(None) is False


def test_rank_advancement_authority_admin_bypasses_scope_checks(app_session):
    _level(app_session, "מדור", 1)
    target = _node(app_session, "מדור")
    admin = _soldier(app_session, "rank_admin", role="admin")

    assert rank_advancement_edit_authorized(app_session, user=admin, target_node=target) is True


def test_rank_advancement_authority_ignores_lower_level_scope_when_user_commands_elsewhere(app_session):
    _level(app_session, "מדור", 1)
    _level(app_session, "ענף", 2)
    commander = _soldier(app_session, "rank_lower_scope", role="commander")
    junior_root = _node(app_session, "ענף", name="Junior", commander_id=commander.id)
    target = _child(app_session, junior_root, "ענף", name="Target")

    assert rank_advancement_edit_authorized(app_session, user=commander, target_node=target) is False


def test_rank_advancement_authority_uses_actual_commander_assignment_not_display_role(app_session):
    _level(app_session, "מדור", 1)
    actor = _soldier(app_session, "rank_actual_commander")
    root = _node(app_session, "מדור", commander_id=actor.id)
    target = _child(app_session, root, "מדור")

    assert rank_advancement_edit_authorized(app_session, user=actor, target_node=target) is True


def test_admin_sees_everything(app_session):
    _level(app_session, "אגף", 1)
    node = _node(app_session, "אגף")
    admin = _soldier(app_session, "100", role="admin")
    assert can_view_soldier_scope(app_session, admin, node) is True


def test_plain_soldier_blocked_by_default(app_session):
    _level(app_session, "אגף", 1)
    node = _node(app_session, "אגף")
    plain = _soldier(app_session, "101")
    assert can_view_soldier_scope(app_session, plain, node) is False


def test_plain_soldier_allowed_when_every_soldier(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    node = _node(app_session, "אגף")
    plain = _soldier(app_session, "102")
    set_setting(app_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
    app_session.flush()
    assert can_view_soldier_scope(app_session, plain, node) is True


def test_commander_sees_own_subtree_always(app_session):
    _level(app_session, "מרכז", 1)
    _level(app_session, "ענף", 2)
    cmd = _soldier(app_session, "103", role="commander")
    root = _node(app_session, "מרכז", commander_id=cmd.id)
    child = _child(app_session, root, "ענף")
    assert can_view_soldier_scope(app_session, cmd, child) is True


def test_commander_cannot_see_outside_subtree_with_zero_expansion(app_session):
    _level(app_session, "מרכז", 1)
    cmd = _soldier(app_session, "104", role="commander")
    _node(app_session, "מרכז", commander_id=cmd.id)
    other = _node(app_session, "מרכז", name="Other")
    assert can_view_soldier_scope(app_session, cmd, other) is False


def test_commander_sees_ancestor_with_levels_above(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "ענף", 3)
    top = _node(app_session, "אגף", name="Top")
    center = _child(app_session, top, "מרכז", name="Center")
    cmd = _soldier(app_session, "105", role="commander")
    branch = _child(app_session, center, "ענף", name="Branch")
    branch.commander_id = cmd.id
    app_session.flush()
    sibling_branch = _child(app_session, center, "ענף", name="SiblingBranch")

    # Without expansion, the commander's peer branch isn't visible.
    assert can_view_soldier_scope(app_session, cmd, sibling_branch) is False

    set_setting(app_session, "transparency.commander_levels_above", 1, actor_id=None)
    app_session.flush()
    # One level up from "ענף" is "מרכז" — the sibling branch is under that same
    # center, so it's now visible.
    assert can_view_soldier_scope(app_session, cmd, sibling_branch) is True


def test_duty_manager_sees_ancestor_with_levels_above(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "ענף", 3)
    top = _node(app_session, "אגף", name="Top")
    center = _child(app_session, top, "מרכז", name="Center")
    dm = _soldier(app_session, "106", role="duty_manager")
    branch = _child(app_session, center, "ענף", name="Branch")
    sibling_branch = _child(app_session, center, "ענף", name="SiblingBranch")
    app_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=branch.id))
    app_session.flush()

    assert can_view_soldier_scope(app_session, dm, sibling_branch) is False

    set_setting(app_session, "transparency.duty_manager_levels_above", 1, actor_id=None)
    app_session.flush()
    assert can_view_soldier_scope(app_session, dm, sibling_branch) is True


def test_senior_enough_commander_sees_unrelated_soldier(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    _level(app_session, "ענף", 2)
    cmd = _soldier(app_session, "107", role="commander")
    _node(app_session, "אגף", commander_id=cmd.id)
    unrelated = _node(app_session, "ענף", name="Unrelated")
    set_setting(app_session, "transparency.min_visible_level", "אגף", actor_id=None)
    app_session.flush()
    assert can_view_soldier_scope(app_session, cmd, unrelated) is True


def test_junior_commander_below_threshold_blocked(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "אגף", 1)
    _level(app_session, "ענף", 2)
    cmd = _soldier(app_session, "108", role="commander")
    _node(app_session, "ענף", commander_id=cmd.id)
    unrelated = _node(app_session, "אגף", name="Unrelated")
    set_setting(app_session, "transparency.min_visible_level", "אגף", actor_id=None)
    app_session.flush()
    assert can_view_soldier_scope(app_session, cmd, unrelated) is False


def test_default_threshold_is_mador_not_every_soldier(app_session):
    """Pins the unset-setting fallback to the specific level "מדור", not the
    fully-open "every_soldier" sentinel -- a מדור commander must see an
    unrelated soldier with NOTHING configured, and a more junior (ענף)
    commander must NOT, purely from the default."""
    _level(app_session, "מדור", 1)
    _level(app_session, "ענף", 2)
    senior_cmd = _soldier(app_session, "112", role="commander")
    _node(app_session, "מדור", commander_id=senior_cmd.id)
    junior_cmd = _soldier(app_session, "113", role="commander")
    _node(app_session, "ענף", commander_id=junior_cmd.id)
    unrelated = _node(app_session, "מדור", name="Unrelated")
    assert can_view_soldier_scope(app_session, senior_cmd, unrelated) is True
    assert can_view_soldier_scope(app_session, junior_cmd, unrelated) is False


def test_has_any_visibility_true_for_any_commanded_node(app_session):
    _level(app_session, "אגף", 1)
    cmd = _soldier(app_session, "109", role="commander")
    _node(app_session, "אגף", commander_id=cmd.id)
    assert has_any_visibility(app_session, cmd) is True


def test_has_any_visibility_false_for_plain_soldier_by_default(app_session):
    plain = _soldier(app_session, "110")
    assert has_any_visibility(app_session, plain) is False


def test_has_any_visibility_true_when_every_soldier(app_session):
    from app.services.settings_loader import set_setting

    plain = _soldier(app_session, "111")
    set_setting(app_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
    app_session.flush()
    assert has_any_visibility(app_session, plain) is True


def test_commander_at_mador_or_above_can_delete_in_subtree(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מדור", 2)
    _level(app_session, "כיתה", 3)
    cmd = _soldier(app_session, "9500001", role="commander")
    root = _node(app_session, "מדור", commander_id=cmd.id)
    target = _child(app_session, root, "כיתה")
    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=target) is True


def test_commander_below_mador_cannot_delete(app_session):
    _level(app_session, "מדור", 1)
    _level(app_session, "כיתה", 2)
    cmd = _soldier(app_session, "9500002", role="commander")
    root = _node(app_session, "כיתה", commander_id=cmd.id)
    target = _child(app_session, root, "כיתה")
    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=target) is False


def test_commander_out_of_scope_cannot_delete(app_session):
    _level(app_session, "מדור", 1)
    cmd = _soldier(app_session, "9500003", role="commander")
    _node(app_session, "מדור", commander_id=cmd.id)
    other_root = _node(app_session, "מדור", name="Other")
    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=other_root) is False


def test_commander_delete_min_level_configurable(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "מדור", 1)
    _level(app_session, "כיתה", 2)
    cmd = _soldier(app_session, "9500004", role="commander")
    root = _node(app_session, "כיתה", commander_id=cmd.id)

    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=root) is False

    set_setting(app_session, "soldiers.commander_delete_min_level", "כיתה", actor_id=None)
    app_session.flush()
    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=root) is True


def test_has_any_commander_delete_scope_true_for_qualifying_commander(app_session):
    _level(app_session, "מדור", 1)
    cmd = _soldier(app_session, "9500005", role="commander")
    _node(app_session, "מדור", commander_id=cmd.id)
    assert has_any_commander_delete_scope(app_session, user=cmd) is True


def test_has_any_commander_delete_scope_false_for_junior_commander(app_session):
    _level(app_session, "מדור", 1)
    _level(app_session, "כיתה", 2)
    cmd = _soldier(app_session, "9500006", role="commander")
    _node(app_session, "כיתה", commander_id=cmd.id)
    assert has_any_commander_delete_scope(app_session, user=cmd) is False
