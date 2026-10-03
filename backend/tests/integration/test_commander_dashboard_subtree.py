from __future__ import annotations

import uuid

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.routes import commander_dashboard
from tests.helpers import create_node


def test_authorized_subtree_ids_matches_legacy_union_with_one_descendant_select(
    admin_session: Session,
):
    root_a = create_node(admin_session, level="group", name=f"subtree-a-{uuid.uuid4().hex}")
    child_a = create_node(
        admin_session, level="branch", name=f"subtree-a-child-{uuid.uuid4().hex}", parent=root_a
    )
    create_node(
        admin_session, level="unit", name=f"subtree-a-grandchild-{uuid.uuid4().hex}", parent=child_a
    )
    root_b = create_node(admin_session, level="group", name=f"subtree-b-{uuid.uuid4().hex}")
    create_node(
        admin_session, level="branch", name=f"subtree-b-child-{uuid.uuid4().hex}", parent=root_b
    )

    root_ids = [root_a.id, child_a.id, root_b.id, root_a.id]
    legacy_ids = {
        node_id
        for root_id in root_ids
        for node_id in commander_dashboard._get_subtree_ids(admin_session, root_id)
    }

    statements: list[str] = []
    bind = admin_session.get_bind()

    def capture(_conn, _cursor, statement, *_):
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        actual_list = commander_dashboard._authorized_subtree_ids(admin_session, root_ids)
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    actual_ids = set(actual_list)
    descendant_selects = [
        " ".join(sql.lower().split())
        for sql in statements
        if "select hierarchy_nodes.id from hierarchy_nodes" in " ".join(sql.lower().split())
    ]
    assert actual_ids == legacy_ids
    assert {root_a.id, child_a.id, root_b.id}.issubset(actual_ids)
    assert len(actual_ids) == len(actual_list)
    assert len(descendant_selects) == 1, statements


def test_authorized_subtree_ids_returns_empty_for_empty_roots_without_query(
    admin_session: Session,
):
    statements: list[str] = []
    bind = admin_session.get_bind()

    def capture(_conn, _cursor, statement, *_):
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        actual_ids = commander_dashboard._authorized_subtree_ids(admin_session, [])
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert actual_ids == []
    assert not any("hierarchy_nodes" in sql.lower() for sql in statements)


def test_authorized_subtree_ids_preserves_missing_root_id(admin_session: Session):
    missing_root_id = uuid.uuid4()

    actual_ids = commander_dashboard._authorized_subtree_ids(admin_session, [missing_root_id])

    assert actual_ids == [missing_root_id]
