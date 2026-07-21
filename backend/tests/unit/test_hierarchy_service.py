import uuid

import pytest
from sqlalchemy import select, text

from app.db.models import HierarchyLevelType, HierarchyNode
from app.services.hierarchy import (
    HierarchyError,
    ReorderViolation,
    ancestor_id_at_level,
    create_level_type,
    create_node,
    delete_level_type,
    delete_node,
    move_node,
    rename_node,
    reorder_level_types,
    set_commander,
)
from tests.helpers import create_node as seed_node
from tests.helpers import create_soldier


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


def test_move_allows_any_level_below(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")
    b1 = seed_node(admin_session, level="branch", name="b1", parent=d1)
    g1 = seed_node(admin_session, level="group", name="g1", parent=b1)
    d2 = seed_node(admin_session, level="department", name="d2")
    move_node(admin_session, node_id=g1.id, new_parent_id=d2.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(g1)
    assert g1.parent_id == d2.id


def test_move_rejects_rank_not_below_new_parent(admin_session):
    dept = seed_node(admin_session, level="department", name="d")  # rank 4
    branch = seed_node(admin_session, level="branch", name="b", parent=dept)  # rank 5
    other_branch = seed_node(admin_session, level="branch", name="b2")  # rank 5
    with pytest.raises(HierarchyError):
        move_node(admin_session, node_id=branch.id, new_parent_id=other_branch.id, actor_id=None)  # 5 <= 5


def test_create_root_allows_any_level(admin_session):
    node = create_node(admin_session, level="division", name="מערך", parent_id=None, actor_id=None)
    admin_session.commit()
    assert node.parent_id is None
    assert node.path_ids == [node.id]


def test_create_child_rejects_rank_not_below_parent(admin_session):
    branch = seed_node(admin_session, level="branch", name="b")  # rank 5
    with pytest.raises(HierarchyError):
        create_node(admin_session, level="department", name="d", parent_id=branch.id, actor_id=None)  # rank 4 <= 5


def test_create_node_rejects_unknown_level(admin_session):
    with pytest.raises(HierarchyError):
        create_node(admin_session, level="not_a_real_level", name="x", parent_id=None, actor_id=None)


def test_ancestor_id_at_level_finds_matching_ancestor(admin_session):
    root = seed_node(admin_session, level="division", name="div_test")
    branch = seed_node(admin_session, level="branch", name="branch_test", parent=root)
    unit = seed_node(admin_session, level="unit", name="unit_test", parent=branch)

    assert ancestor_id_at_level(admin_session, unit.id, "branch") == branch.id
    assert ancestor_id_at_level(admin_session, unit.id, "division") == root.id
    assert ancestor_id_at_level(admin_session, unit.id, "nonexistent_level") is None


def test_ancestor_id_at_level_returns_none_for_missing_node(admin_session):
    assert ancestor_id_at_level(admin_session, uuid.uuid4(), "division") is None


def test_create_child_allows_any_level_below(admin_session):
    dept = seed_node(admin_session, level="department", name="חיל")
    team = create_node(
        admin_session, level="team", name="צוות", parent_id=dept.id, actor_id=None
    )
    admin_session.commit()
    assert team.path_ids == [dept.id, team.id]


def test_create_writes_audit(admin_session):
    create_node(admin_session, level="corps", name="כלל המסגרת", parent_id=None, actor_id=None)
    admin_session.commit()
    row = admin_session.execute(
        text(
            "SELECT action FROM audit_log WHERE action='hierarchy_node.create' ORDER BY created_at DESC LIMIT 1"
        )
    ).first()
    assert row is not None


def test_rename_node(admin_session):
    d = seed_node(admin_session, level="department", name="old")
    rename_node(admin_session, node_id=d.id, name="new", actor_id=None)
    admin_session.commit()
    admin_session.refresh(d)
    assert d.name == "new"


def test_set_commander(admin_session):
    d = seed_node(admin_session, level="department", name="d")
    cmd = create_soldier(admin_session, personal_number="8000001", role="commander")
    set_commander(admin_session, node_id=d.id, commander_id=cmd.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(d)
    assert d.commander_id == cmd.id


def test_delete_node_rejected_with_children(admin_session):
    d = seed_node(admin_session, level="department", name="d")
    seed_node(admin_session, level="branch", name="b", parent=d)
    with pytest.raises(HierarchyError):
        delete_node(admin_session, node_id=d.id, actor_id=None)


def test_delete_node_rejected_with_soldiers(admin_session):
    d = seed_node(admin_session, level="department", name="d")
    create_soldier(admin_session, personal_number="8000002", hierarchy_node_id=d.id)
    with pytest.raises(HierarchyError):
        delete_node(admin_session, node_id=d.id, actor_id=None)


def test_delete_empty_node(admin_session):
    d = seed_node(admin_session, level="department", name="d")
    delete_node(admin_session, node_id=d.id, actor_id=None)
    admin_session.commit()
    assert admin_session.get(HierarchyNode, d.id) is None


def test_create_level_type_appends_at_max_rank_plus_one(admin_session):
    lt = create_level_type(admin_session, key="platoon", label="מחלקה", actor_id=None)
    admin_session.commit()
    assert lt.rank == 8  # 7 seeded types, ranks 1..7


def test_create_level_type_rejects_duplicate_key(admin_session):
    with pytest.raises(HierarchyError):
        create_level_type(admin_session, key="branch", label="ענף 2", actor_id=None)


def test_delete_level_type_rejected_if_in_use(admin_session):
    branch_type = admin_session.execute(
        select(HierarchyLevelType).where(HierarchyLevelType.key == "branch")
    ).scalar_one()
    seed_node(admin_session, level="branch", name="b")
    with pytest.raises(HierarchyError):
        delete_level_type(admin_session, id=branch_type.id, actor_id=None)


def test_delete_level_type_succeeds_when_unused(admin_session):
    lt = create_level_type(admin_session, key="platoon", label="מחלקה", actor_id=None)
    admin_session.commit()
    delete_level_type(admin_session, id=lt.id, actor_id=None)
    admin_session.commit()
    assert admin_session.get(HierarchyLevelType, lt.id) is None


def test_reorder_level_types_happy_path(admin_session):
    types = admin_session.execute(
        select(HierarchyLevelType).order_by(HierarchyLevelType.rank)
    ).scalars().all()
    reversed_ids = [t.id for t in reversed(types)]
    reorder_level_types(admin_session, ordered_ids=reversed_ids, actor_id=None)
    admin_session.commit()
    by_id = {
        t.id: t.rank
        for t in admin_session.execute(select(HierarchyLevelType)).scalars().all()
    }
    assert by_id[reversed_ids[0]] == 1
    assert by_id[reversed_ids[-1]] == len(reversed_ids)


def test_reorder_level_types_rejects_partial_id_list(admin_session):
    types = admin_session.execute(
        select(HierarchyLevelType).order_by(HierarchyLevelType.rank)
    ).scalars().all()
    with pytest.raises(HierarchyError):
        reorder_level_types(admin_session, ordered_ids=[types[0].id], actor_id=None)


def test_reorder_level_types_detects_tree_violation(admin_session):
    dept = seed_node(admin_session, level="department", name="d")  # rank 4
    seed_node(admin_session, level="branch", name="b", parent=dept)  # rank 5
    types = {
        t.key: t
        for t in admin_session.execute(select(HierarchyLevelType)).scalars().all()
    }
    # Move "branch" (currently rank 5) above "department" (rank 4) -> would invert the pair.
    ordered = sorted(types.values(), key=lambda t: t.rank)
    ordered_ids = [t.id for t in ordered]
    dept_pos = next(i for i, t in enumerate(ordered) if t.key == "department")
    branch_pos = next(i for i, t in enumerate(ordered) if t.key == "branch")
    ordered_ids[dept_pos], ordered_ids[branch_pos] = ordered_ids[branch_pos], ordered_ids[dept_pos]
    with pytest.raises(ReorderViolation) as exc_info:
        reorder_level_types(admin_session, ordered_ids=ordered_ids, actor_id=None)
    assert len(exc_info.value.violations) == 1
    assert exc_info.value.violations[0]["parent"] == "d (מרכז)"
    assert exc_info.value.violations[0]["child"] == "b (ענף)"


def test_reorder_level_types_detects_multiple_violations(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")  # rank 4
    seed_node(admin_session, level="branch", name="b1", parent=d1)  # rank 5
    d2 = seed_node(admin_session, level="department", name="d2")  # rank 4
    seed_node(admin_session, level="branch", name="b2", parent=d2)  # rank 5
    types = {
        t.key: t
        for t in admin_session.execute(select(HierarchyLevelType)).scalars().all()
    }
    # Move "branch" (currently rank 5) above "department" (rank 4) -> inverts both pairs.
    ordered = sorted(types.values(), key=lambda t: t.rank)
    ordered_ids = [t.id for t in ordered]
    dept_pos = next(i for i, t in enumerate(ordered) if t.key == "department")
    branch_pos = next(i for i, t in enumerate(ordered) if t.key == "branch")
    ordered_ids[dept_pos], ordered_ids[branch_pos] = ordered_ids[branch_pos], ordered_ids[dept_pos]
    with pytest.raises(ReorderViolation) as exc_info:
        reorder_level_types(admin_session, ordered_ids=ordered_ids, actor_id=None)
    assert len(exc_info.value.violations) == 2
    actual_pairs = {
        (v["parent"], v["child"]) for v in exc_info.value.violations
    }
    expected_pairs = {
        ("d1 (מרכז)", "b1 (ענף)"),
        ("d2 (מרכז)", "b2 (ענף)"),
    }
    assert actual_pairs == expected_pairs
