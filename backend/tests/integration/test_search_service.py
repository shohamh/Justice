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
