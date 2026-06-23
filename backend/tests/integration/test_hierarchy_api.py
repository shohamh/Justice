import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_creates_division_then_unit(client: TestClient, admin_session: Session):
    corps = create_node(admin_session, level="corps", name="כלל המסגרת")
    admin_session.commit()
    admin = create_soldier(admin_session, personal_number="5000001", role="admin")
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "division", "name": "מערך", "parent_id": str(corps.id)},
    )
    assert r.status_code == 201
    div_id = r.json()["id"]
    r2 = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "unit", "name": "יחידה", "parent_id": div_id},
    )
    assert r2.status_code == 201
    assert r2.json()["path_ids"] == [str(corps.id), div_id, r2.json()["id"]]


def test_create_any_level_below_allowed(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000002", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "team", "name": "צוות", "parent_id": str(dept.id)},
    )
    assert r.status_code == 201


def test_plain_soldier_cannot_create_node(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5000003", role="soldier")
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(s),
        json={"level": "department", "name": "x", "parent_id": None},
    )
    assert r.status_code == 403


def test_get_tree_scoped_for_duty_manager(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(
        admin_session, personal_number="5000004", role="duty_manager", hierarchy_node_id=b.id
    )
    admin_session.commit()
    r = client.get("/api/hierarchy/tree", headers=auth_headers(dm))
    assert r.status_code == 200
    ids = {n["id"] for n in r.json()}
    assert str(b.id) in ids
    assert str(other.id) not in ids


def test_list_level_types_ordered_by_rank(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5000010", role="soldier")
    r = client.get("/api/hierarchy/level-types", headers=auth_headers(s))
    assert r.status_code == 200
    ranks = [t["rank"] for t in r.json()]
    assert ranks == sorted(ranks)


def test_create_level_type_as_admin(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000011", role="admin")
    r = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(admin),
        json={"key": "platoon", "label": "מחלקה"},
    )
    assert r.status_code == 201
    assert r.json()["key"] == "platoon"


def test_create_level_type_rejects_soldier(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5000012", role="soldier")
    r = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(s),
        json={"key": "platoon", "label": "מחלקה"},
    )
    assert r.status_code == 403


def test_create_level_type_duplicate_key_409(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000013", role="admin")
    r = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(admin),
        json={"key": "branch", "label": "ענף 2"},
    )
    assert r.status_code == 409


def test_delete_level_type_in_use_409(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000014", role="admin")
    create_node(admin_session, level="branch", name="b")
    admin_session.commit()
    branch_id = admin_session.execute(
        text("SELECT id FROM hierarchy_level_types WHERE key = 'branch'")
    ).scalar_one()
    r = client.delete(f"/api/hierarchy/level-types/{branch_id}", headers=auth_headers(admin))
    assert r.status_code == 409


def test_delete_level_type_not_found_404(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000019", role="admin")
    r = client.delete(f"/api/hierarchy/level-types/{uuid.uuid4()}", headers=auth_headers(admin))
    assert r.status_code == 404


def test_reorder_level_types_violation_returns_409_with_violations(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="5000015", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    create_node(admin_session, level="branch", name="b", parent=dept)
    admin_session.commit()
    rows = admin_session.execute(
        text("SELECT id, key FROM hierarchy_level_types ORDER BY rank")
    ).all()
    ordered_ids = [str(r.id) for r in rows]
    dept_pos = next(i for i, r in enumerate(rows) if r.key == "department")
    branch_pos = next(i for i, r in enumerate(rows) if r.key == "branch")
    ordered_ids[dept_pos], ordered_ids[branch_pos] = ordered_ids[branch_pos], ordered_ids[dept_pos]
    r = client.put(
        "/api/hierarchy/level-types/reorder",
        headers=auth_headers(admin),
        json={"ordered_ids": ordered_ids},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["detail"] == "reorder_would_violate_tree"
    assert len(r.json()["detail"]["violations"]) == 1


def test_patch_node_changes_level_when_valid(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000016", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    branch = create_node(admin_session, level="branch", name="b", parent=dept)
    admin_session.commit()
    r = client.patch(
        f"/api/hierarchy/nodes/{branch.id}",
        headers=auth_headers(admin),
        json={"level": "group"},
    )
    assert r.status_code == 200
    assert r.json()["level"] == "group"


def test_patch_node_rejects_level_violating_position(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000017", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    branch = create_node(admin_session, level="branch", name="b", parent=dept)
    admin_session.commit()
    r = client.patch(
        f"/api/hierarchy/nodes/{branch.id}",
        headers=auth_headers(admin),
        json={"level": "corps"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_level_for_position"


def test_create_node_with_custom_level_type(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000018", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r0 = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(admin),
        json={"key": "platoon", "label": "מחלקה"},
    )
    assert r0.status_code == 201
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "platoon", "name": "מחלקה א", "parent_id": str(dept.id)},
    )
    assert r.status_code == 201
