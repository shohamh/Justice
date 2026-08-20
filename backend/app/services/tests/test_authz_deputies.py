from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.auth.authz import commanded_node_ids, dm_scope_node_ids, is_commander, is_duty_manager
from app.db.models import DutyManagerScope, RoleDeputy
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_commanded_node_ids_includes_own_commanded_node(admin_session):
    cmd = create_soldier(admin_session, personal_number=f"a_{_uid()}", role="commander")
    node = create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=cmd.id)
    assert commanded_node_ids(admin_session, cmd.id) == {node.id}


def test_commanded_node_ids_includes_active_deputy_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"b_{_uid()}", role="commander")
    node = create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"c_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today() - timedelta(days=1), end_date=date.today() + timedelta(days=1),
    ))
    admin_session.commit()

    assert commanded_node_ids(admin_session, deputy.id) == {node.id}
    assert is_commander(admin_session, deputy.id) is True


def test_commanded_node_ids_excludes_expired_deputy_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"d_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"e_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today() - timedelta(days=10), end_date=date.today() - timedelta(days=1),
    ))
    admin_session.commit()

    assert commanded_node_ids(admin_session, deputy.id) == set()
    assert is_commander(admin_session, deputy.id) is False


def test_commanded_node_ids_excludes_future_deputy_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"f_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"g_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=10),
    ))
    admin_session.commit()

    assert commanded_node_ids(admin_session, deputy.id) == set()


def test_dm_scope_node_ids_includes_active_deputy_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"h_{_uid()}", role="duty_manager")
    node = create_node(admin_session, level="team", name=f"n_{_uid()}")
    admin_session.add(DutyManagerScope(duty_manager_id=principal.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"i_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="duty_manager",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert dm_scope_node_ids(admin_session, deputy.id) == {node.id}
    assert is_duty_manager(admin_session, deputy.id) is True


def test_commander_deputy_grant_does_not_grant_duty_manager_scope(admin_session):
    """role='commander' grants must not leak into dm_scope_node_ids, and vice versa."""
    principal = create_soldier(admin_session, personal_number=f"j_{_uid()}", role="commander")
    node = create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"k_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert commanded_node_ids(admin_session, deputy.id) == {node.id}
    assert dm_scope_node_ids(admin_session, deputy.id) == set()
