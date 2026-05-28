import pytest

from app.services.hierarchy import HierarchyError, create_node
from tests.helpers import create_node as seed_node


from app.services.hierarchy import move_node


def test_move_recomputes_path_ids_for_node_and_descendants(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")
    b1 = seed_node(admin_session, level="branch", name="b1", parent=d1)
    g1 = seed_node(admin_session, level="group", name="g1", parent=b1)
    t1 = seed_node(admin_session, level="team", name="t1", parent=g1)
    d2 = seed_node(admin_session, level="department", name="d2")
    b2 = seed_node(admin_session, level="branch", name="b2", parent=d2)

    move_node(admin_session, node_id=g1.id, new_parent_id=b2.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(g1)
    admin_session.refresh(t1)
    assert g1.path_ids == [d2.id, b2.id, g1.id]
    assert t1.path_ids == [d2.id, b2.id, g1.id, t1.id]


def test_move_rejects_cycle(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")
    b1 = seed_node(admin_session, level="branch", name="b1", parent=d1)
    g1 = seed_node(admin_session, level="group", name="g1", parent=b1)
    with pytest.raises(HierarchyError):
        move_node(admin_session, node_id=b1.id, new_parent_id=g1.id, actor_id=None)


def test_move_enforces_level_rules(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")
    b1 = seed_node(admin_session, level="branch", name="b1", parent=d1)
    g1 = seed_node(admin_session, level="group", name="g1", parent=b1)
    d2 = seed_node(admin_session, level="department", name="d2")
    with pytest.raises(HierarchyError):
        move_node(admin_session, node_id=g1.id, new_parent_id=d2.id, actor_id=None)


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
