from __future__ import annotations

import uuid

from tests.helpers import create_node, create_soldier

from app.services.import_scope import is_node_in_actor_scope


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_admin_always_in_scope(admin_session):
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    assert is_node_in_actor_scope(session=admin_session, actor=admin, node_id=node.id) is True


def test_admin_in_scope_even_with_none_node(admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    assert is_node_in_actor_scope(session=admin_session, actor=admin, node_id=None) is True


def test_dm_node_within_scope(admin_session):
    from app.db.models import DutyManagerScope

    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    child = create_node(admin_session, level="team", name=f"team_{_uid()}", parent=node)
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()

    assert is_node_in_actor_scope(session=admin_session, actor=dm, node_id=child.id) is True


def test_dm_node_outside_scope(admin_session):
    from app.db.models import DutyManagerScope

    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    other_node = create_node(admin_session, level="division", name=f"other_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()

    assert is_node_in_actor_scope(session=admin_session, actor=dm, node_id=other_node.id) is False


def test_dm_none_node_out_of_scope(admin_session):
    from app.db.models import DutyManagerScope

    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()

    assert is_node_in_actor_scope(session=admin_session, actor=dm, node_id=None) is False


def test_dm_no_scope_entries_out_of_scope(admin_session):
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.commit()

    assert is_node_in_actor_scope(session=admin_session, actor=dm, node_id=node.id) is False
