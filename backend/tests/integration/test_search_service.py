from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.search import search_soldiers
from tests.helpers import create_node, create_soldier


def test_search_soldiers_admin_sees_everyone(admin_session: Session):
    dept = create_node(admin_session, level="department", name="search-dept")
    admin = create_soldier(admin_session, personal_number="7200001", role="admin")
    s1 = create_soldier(admin_session, personal_number="7200002", role="soldier", hierarchy_node_id=dept.id)
    admin_session.commit()

    results = search_soldiers(admin_session, user=admin, query="720000")

    ids = {r["id"] for r in results}
    assert str(s1.id) in ids
    assert str(admin.id) in ids


def test_search_soldiers_plain_soldier_only_sees_own_scope(admin_session: Session):
    dept = create_node(admin_session, level="department", name="search-dept-2")
    other_dept = create_node(admin_session, level="department", name="search-dept-3")
    plain = create_soldier(admin_session, personal_number="7200010", role="soldier", hierarchy_node_id=dept.id)
    same_scope = create_soldier(admin_session, personal_number="7200011", role="soldier", hierarchy_node_id=dept.id)
    other_scope = create_soldier(admin_session, personal_number="7200012", role="soldier", hierarchy_node_id=other_dept.id)
    admin_session.commit()

    results = search_soldiers(admin_session, user=plain, query="72000")

    ids = {r["id"] for r in results}
    assert str(plain.id) in ids
    assert str(same_scope.id) not in ids
    assert str(other_scope.id) not in ids


def test_search_soldiers_matches_full_name_case_insensitive(admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7200020", role="admin")
    target = create_soldier(admin_session, personal_number="7200021", role="soldier")
    target.full_name = "Yossi Cohen"
    admin_session.commit()

    results = search_soldiers(admin_session, user=admin, query="yossi")

    assert any(r["id"] == str(target.id) for r in results)


def test_search_soldiers_excludes_left_soldiers(admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7200030", role="admin")
    left = create_soldier(admin_session, personal_number="7200031", role="soldier")
    from datetime import date
    left.left_at = date(2020, 1, 1)
    admin_session.commit()

    results = search_soldiers(admin_session, user=admin, query="720003")

    assert not any(r["id"] == str(left.id) for r in results)


def test_search_soldiers_respects_limit(admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7200040", role="admin")
    for i in range(10):
        create_soldier(admin_session, personal_number=f"73000{i:02d}", role="soldier")
    admin_session.commit()

    results = search_soldiers(admin_session, user=admin, query="7300", limit=3)

    assert len(results) == 3
