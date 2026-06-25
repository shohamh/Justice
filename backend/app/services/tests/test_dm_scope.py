from __future__ import annotations

import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import DutyManagerScope
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_duty_manager_scope_insert(admin_session):
    """DutyManagerScope row can be inserted and its id auto-populated."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)
    assert entry.id is not None


def test_duty_manager_scope_unique_constraint(admin_session):
    """Duplicate (duty_manager_id, hierarchy_node_id) raises IntegrityError."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()


def test_ranks_rasan_and_above_contents():
    from app.services.eligibility import RANKS_RASAN_AND_ABOVE
    assert RANKS_RASAN_AND_ABOVE[0] == "רסן"
    assert "סרן" not in RANKS_RASAN_AND_ABOVE
    assert "סאל" in RANKS_RASAN_AND_ABOVE
    assert "אלוף" in RANKS_RASAN_AND_ABOVE


def test_scope_root_ids_dm_multi_node(admin_session):
    """DM with two DutyManagerScope entries gets both node IDs as roots."""
    from app.db.models import DutyManagerScope
    node1 = create_node(admin_session, level="division", name=f"div1_{_uid()}")
    node2 = create_node(admin_session, level="division", name=f"div2_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node1.id))
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node2.id))
    admin_session.commit()

    from app.auth.authz import scope_root_ids
    roots = scope_root_ids(admin_session, dm)
    assert node1.id in roots
    assert node2.id in roots


def test_scope_root_ids_dm_no_entries(admin_session):
    """DM with no scope entries gets empty root set (not hierarchy_node_id)."""
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.commit()

    from app.auth.authz import scope_root_ids
    roots = scope_root_ids(admin_session, dm)
    assert roots == set()


def test_dm_scope_manage_requires_rasan(admin_session):
    """Commander with rank רסן can DM_SCOPE_MANAGE; rank סרן cannot."""
    from app.auth.authz import can, scope_root_ids, Action
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    high_cmd = create_soldier(admin_session, personal_number=f"cmd_h_{_uid()}", role="commander")
    high_cmd.rank = "רסן"
    high_cmd.hierarchy_node_id = node.id
    node.commander_id = high_cmd.id
    low_cmd = create_soldier(admin_session, personal_number=f"cmd_l_{_uid()}", role="commander")
    low_cmd.rank = "סרן"
    admin_session.commit()

    roots_h = scope_root_ids(admin_session, high_cmd)
    roots_l = scope_root_ids(admin_session, low_cmd)

    assert can(high_cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots_h)
    assert not can(low_cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots_l)


def test_dm_scope_manage_null_rank_denied(admin_session):
    """Commander with null rank cannot DM_SCOPE_MANAGE."""
    from app.auth.authz import can, scope_root_ids, Action
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    cmd.rank = None
    node.commander_id = cmd.id
    cmd.hierarchy_node_id = node.id
    admin_session.commit()

    roots = scope_root_ids(admin_session, cmd)
    assert not can(cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots)


def test_assign_dm_scope_grants_dm_role(admin_session):
    """assign_dm_scope on a plain soldier grants duty_manager role."""
    from app.db.models import DutyManagerScope
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    s = create_soldier(admin_session, personal_number=f"s_{_uid()}", role="soldier")

    from app.services.dm_scope import assign_dm_scope
    assign_dm_scope(admin_session, soldier_id=s.id, node_id=node.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(s)

    assert s.role == "duty_manager"


def test_assign_dm_scope_idempotent(admin_session):
    """Calling assign_dm_scope twice for the same (soldier, node) returns the same entry."""
    from app.db.models import DutyManagerScope
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    s = create_soldier(admin_session, personal_number=f"s_{_uid()}", role="soldier")

    from app.services.dm_scope import assign_dm_scope
    e1 = assign_dm_scope(admin_session, soldier_id=s.id, node_id=node.id, actor_id=None)
    admin_session.commit()
    e2 = assign_dm_scope(admin_session, soldier_id=s.id, node_id=node.id, actor_id=None)
    admin_session.commit()

    assert e1.id == e2.id


def test_assign_dm_scope_does_not_change_admin_role(admin_session):
    """assign_dm_scope does not downgrade an admin's role."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    from app.services.dm_scope import assign_dm_scope
    assign_dm_scope(admin_session, soldier_id=admin.id, node_id=node.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(admin)

    assert admin.role == "admin"


def test_remove_dm_scope_downgrades_to_soldier_when_last(admin_session):
    """Removing the last scope entry downgrades role to soldier."""
    from app.db.models import DutyManagerScope
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    # Create DM without hierarchy_node_id so helpers.py doesn't auto-create a scope entry
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)

    from app.services.dm_scope import remove_dm_scope
    remove_dm_scope(admin_session, entry_id=entry.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(dm)

    assert dm.role == "soldier"


def test_remove_dm_scope_downgrades_to_commander_if_commands_node(admin_session):
    """Removing the last scope entry keeps commander role if soldier commands a node."""
    from app.db.models import DutyManagerScope
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    node.commander_id = dm.id
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)

    from app.services.dm_scope import remove_dm_scope
    remove_dm_scope(admin_session, entry_id=entry.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(dm)

    assert dm.role == "commander"


def test_scope_root_ids_includes_dm_nodes_regardless_of_role_label(admin_session):
    """A soldier labeled 'commander' who also holds a DutyManagerScope row must still
    get that node in their roots — scope_root_ids must not gate DM nodes on role=='duty_manager'."""
    from app.db.models import DutyManagerScope
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    admin_session.add(DutyManagerScope(duty_manager_id=cmd.id, hierarchy_node_id=node.id))
    admin_session.commit()

    from app.auth.authz import scope_root_ids
    roots = scope_root_ids(admin_session, cmd)
    assert node.id in roots


def test_is_commander_and_is_duty_manager_helpers(admin_session):
    from app.auth.authz import is_commander, is_duty_manager
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    node.commander_id = cmd.id
    plain = create_soldier(admin_session, personal_number=f"s_{_uid()}", role="soldier")
    admin_session.commit()

    assert is_commander(admin_session, cmd.id) is True
    assert is_duty_manager(admin_session, cmd.id) is False
    assert is_commander(admin_session, plain.id) is False
    assert is_duty_manager(admin_session, plain.id) is False


def test_remove_dm_scope_keeps_dm_role_if_other_entries_remain(admin_session):
    """Removing one of multiple scope entries keeps duty_manager role."""
    from app.db.models import DutyManagerScope
    node1 = create_node(admin_session, level="division", name=f"div1_{_uid()}")
    node2 = create_node(admin_session, level="division", name=f"div2_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    e1 = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node1.id)
    e2 = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node2.id)
    admin_session.add_all([e1, e2])
    admin_session.commit()
    admin_session.refresh(e1)

    from app.services.dm_scope import remove_dm_scope
    remove_dm_scope(admin_session, entry_id=e1.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(dm)

    assert dm.role == "duty_manager"
