# backend/app/services/tests/test_authority.py
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from app.db.models import HierarchyLevelType, HierarchyNode, Soldier
from app.services.authority import commander_can_grant_commander_exemption, dm_scope_covers_level


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


def test_commander_below_rasan_without_hamador_command_cannot_grant(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "פלוגה", 2)
    _level(app_session, "מדור", 3)
    node = HierarchyNode(level="פלוגה", name="Co", path_ids=[])
    app_session.add(node)
    app_session.flush()
    node.path_ids = [node.id]
    s = Soldier(personal_number="1", full_name="X", password_hash="x", rank="סרן")
    app_session.add(s)
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=s.id, commander_rank=s.rank) is False


def test_commander_rasan_can_grant_regardless_of_command_level(app_session):
    s = Soldier(personal_number="2", full_name="X", password_hash="x", rank="רסן")
    app_session.add(s)
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=s.id, commander_rank=s.rank) is True


def test_commander_of_mador_or_above_can_grant_even_below_rasan(app_session):
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
    assert commander_can_grant_commander_exemption(app_session, commander_id=s.id, commander_rank=s.rank) is True


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
    assert commander_can_grant_commander_exemption(app_session, commander_id=cmd.id, commander_rank=None) is False

    # Lower the required threshold to "צוות" via setting — now they should qualify.
    set_setting(app_session, "exemptions.commander_exemption_min_level", "צוות", actor_id=None)
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=cmd.id, commander_rank=None) is True


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
