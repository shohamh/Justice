from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType
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


def test_search_soldiers_commander_sees_descendant_subtree_soldier(admin_session: Session):
    """A commander's scope_root_ids expands to the whole subtree under the node they
    command, not just that exact node — this exercises the `_scoped_node_ids` descendant
    expansion (via `any(r in target.path_ids for r in roots)`) with a real non-empty
    `roots` set, which was previously never hit by any test."""
    commander = create_soldier(admin_session, personal_number="7500001", role="soldier")
    parent = create_node(admin_session, level="department", name="cmd-scope-parent-s", commander_id=commander.id)
    child = create_node(admin_session, level="team", name="cmd-scope-child-s", parent=parent)
    target = create_soldier(admin_session, personal_number="7500002", role="soldier", hierarchy_node_id=child.id)
    sibling_node = create_node(admin_session, level="team", name="cmd-scope-sibling-s")
    sibling = create_soldier(admin_session, personal_number="7500003", role="soldier", hierarchy_node_id=sibling_node.id)
    admin_session.commit()

    results = search_soldiers(admin_session, user=commander, query="750000")

    ids = {r["id"] for r in results}
    assert str(target.id) in ids
    assert str(sibling.id) not in ids


def _make_shift(session: Session, *, duty_type_name: str, start_date, end_date, soldier=None) -> DutyShift:
    dt = DutyType(name=duty_type_name, score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="מוצב-search")
    session.add_all([dt, loc])
    session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id, start_date=start_date, end_date=end_date
    )
    session.add(shift)
    session.flush()
    if soldier is not None:
        session.add(
            DutyAssignment(
                soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
                start_date=start_date, end_date=end_date, duty_shift_id=shift.id,
            )
        )
    session.commit()
    return shift


def test_search_duties_admin_matches_duty_type_name(admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7300001", role="admin")
    from datetime import date
    shift = _make_shift(admin_session, duty_type_name="שמירה-search-unique", start_date=date(2026, 8, 1), end_date=date(2026, 8, 2))

    from app.services.search import search_duties
    results = search_duties(admin_session, user=admin, query="search-unique")

    assert any(r["id"] == str(shift.id) for r in results)


def test_search_duties_plain_soldier_only_sees_own_scope_shifts(admin_session: Session):
    from datetime import date
    from app.services.search import search_duties

    dept = create_node(admin_session, level="department", name="duty-search-dept")
    other_dept = create_node(admin_session, level="department", name="duty-search-dept-2")
    plain = create_soldier(admin_session, personal_number="7300010", role="soldier", hierarchy_node_id=dept.id)
    other = create_soldier(admin_session, personal_number="7300011", role="soldier", hierarchy_node_id=other_dept.id)
    in_scope_shift = _make_shift(
        admin_session, duty_type_name="שמירה-scope-a", start_date=date(2026, 8, 3), end_date=date(2026, 8, 4), soldier=plain,
    )
    out_of_scope_shift = _make_shift(
        admin_session, duty_type_name="שמירה-scope-b", start_date=date(2026, 8, 5), end_date=date(2026, 8, 6), soldier=other,
    )

    results = search_duties(admin_session, user=plain, query="שמירה-scope")

    ids = {r["id"] for r in results}
    assert str(in_scope_shift.id) in ids
    assert str(out_of_scope_shift.id) not in ids


def test_search_duties_commander_sees_descendant_subtree_duty(admin_session: Session):
    """Same descendant-expansion coverage as above, but for search_duties: the target
    shift's assigned soldier sits under a child of the node the commander commands."""
    from datetime import date
    from app.services.search import search_duties

    commander = create_soldier(admin_session, personal_number="7500010", role="soldier")
    parent = create_node(admin_session, level="department", name="cmd-duty-parent", commander_id=commander.id)
    child = create_node(admin_session, level="team", name="cmd-duty-child", parent=parent)
    target_soldier = create_soldier(admin_session, personal_number="7500011", role="soldier", hierarchy_node_id=child.id)
    sibling_node = create_node(admin_session, level="team", name="cmd-duty-sibling")
    sibling_soldier = create_soldier(admin_session, personal_number="7500012", role="soldier", hierarchy_node_id=sibling_node.id)

    in_scope_shift = _make_shift(
        admin_session, duty_type_name="שמירה-cmdscope-a", start_date=date(2026, 8, 7), end_date=date(2026, 8, 8), soldier=target_soldier,
    )
    out_of_scope_shift = _make_shift(
        admin_session, duty_type_name="שמירה-cmdscope-b", start_date=date(2026, 8, 9), end_date=date(2026, 8, 10), soldier=sibling_soldier,
    )

    results = search_duties(admin_session, user=commander, query="שמירה-cmdscope")

    ids = {r["id"] for r in results}
    assert str(in_scope_shift.id) in ids
    assert str(out_of_scope_shift.id) not in ids


from app.services.search import search_units


def test_search_units_admin_matches_any_node(admin_session: Session):
    admin = create_soldier(admin_session, personal_number="7400001", role="admin")
    node = create_node(admin_session, level="department", name="unit-search-unique")

    results = search_units(admin_session, user=admin, query="unit-search-unique")

    assert any(r["id"] == str(node.id) for r in results)


def test_search_units_plain_soldier_sees_only_own_subtree(admin_session: Session):
    dept = create_node(admin_session, level="department", name="unit-scope-dept")
    branch = create_node(admin_session, level="branch", name="unit-scope-branch", parent=dept)
    other_dept = create_node(admin_session, level="department", name="unit-scope-other")
    plain = create_soldier(admin_session, personal_number="7400010", role="soldier", hierarchy_node_id=branch.id)
    admin_session.commit()

    results = search_units(admin_session, user=plain, query="unit-scope")

    ids = {r["id"] for r in results}
    assert str(other_dept.id) not in ids


def test_search_units_commander_sees_descendant_subtree_node(admin_session: Session):
    """Same descendant-expansion coverage as above, but for search_units: the target
    node is a child of the node the commander commands, not the commanded node itself."""
    commander = create_soldier(admin_session, personal_number="7500020", role="soldier")
    parent = create_node(admin_session, level="department", name="cmd-unit-parent", commander_id=commander.id)
    child = create_node(admin_session, level="team", name="cmd-unit-child", parent=parent)
    sibling = create_node(admin_session, level="team", name="cmd-unit-sibling")
    admin_session.commit()

    results = search_units(admin_session, user=commander, query="cmd-unit")

    ids = {r["id"] for r in results}
    assert str(child.id) in ids
    assert str(sibling.id) not in ids
