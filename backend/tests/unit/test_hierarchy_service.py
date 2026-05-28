import pytest

from app.services.hierarchy import HierarchyError, create_node
from tests.helpers import create_node as seed_node


def test_create_root_must_be_department(admin_session):
    node = create_node(admin_session, level="department", name="חיל", parent_id=None, actor_id=None)
    admin_session.commit()
    assert node.parent_id is None
    assert node.path_ids == [node.id]


def test_create_non_department_root_rejected(admin_session):
    with pytest.raises(HierarchyError):
        create_node(admin_session, level="branch", name="ענף", parent_id=None, actor_id=None)


def test_create_child_must_be_exactly_one_level_down(admin_session):
    dept = seed_node(admin_session, level="department", name="חיל")
    branch = create_node(admin_session, level="branch", name="ענף", parent_id=dept.id, actor_id=None)
    admin_session.commit()
    assert branch.path_ids == [dept.id, branch.id]
    with pytest.raises(HierarchyError):
        create_node(admin_session, level="team", name="צוות", parent_id=dept.id, actor_id=None)


def test_create_writes_audit(admin_session):
    from sqlalchemy import text
    create_node(admin_session, level="department", name="חיל", parent_id=None, actor_id=None)
    admin_session.commit()
    row = admin_session.execute(text(
        "SELECT action FROM audit_log WHERE action='hierarchy_node.create' ORDER BY created_at DESC LIMIT 1"
    )).first()
    assert row is not None
