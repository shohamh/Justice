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
