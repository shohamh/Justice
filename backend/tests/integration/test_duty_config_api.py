from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_creates_and_lists_duty_type(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100001", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-א", "score_per_day": "1.50", "is_external": False},
    )
    assert r.status_code == 201, r.text
    dt_id = r.json()["id"]
    r2 = client.get("/api/duty-config/duty-types", headers=auth_headers(admin))
    assert r2.status_code == 200
    assert any(d["id"] == dt_id for d in r2.json())


def test_duty_manager_allowed(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="department", name="dc-dm-node")
    dm = create_soldier(
        admin_session, personal_number="5100002", role="duty_manager", hierarchy_node_id=node.id
    )
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(dm),
        json={"name": "ניקיון-א", "score_per_day": "1.00", "is_external": False},
    )
    assert r.status_code == 201


def test_plain_soldier_forbidden(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5100003", role="soldier")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(s),
        json={"name": "x", "score_per_day": "1.00"},
    )
    assert r.status_code == 403


def test_commander_forbidden(client: TestClient, admin_session: Session):
    # GET is open to any authenticated soldier (reference data); mutation is still gated.
    c = create_soldier(admin_session, personal_number="5100004", role="commander")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(c),
        json={"name": "y", "score_per_day": "1.00"},
    )
    assert r.status_code == 403


def test_plain_soldier_can_list_duty_types(client, admin_session):
    from tests.helpers import create_soldier, auth_headers
    from app.db.models import DutyType

    dt = DutyType(name="plain_soldier_read_test", score_per_day=1)
    admin_session.add(dt)
    admin_session.commit()

    s = create_soldier(admin_session, personal_number="7800001")
    r = client.get("/api/duty-config/duty-types", headers=auth_headers(s))
    assert r.status_code == 200
    assert any(d["name"] == "plain_soldier_read_test" for d in r.json())


def test_plain_soldier_cannot_create_duty_type(client, admin_session):
    from tests.helpers import create_soldier, auth_headers

    s = create_soldier(admin_session, personal_number="7800002")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(s),
        json={"name": "should_not_be_allowed", "score_per_day": "1"},
    )
    assert r.status_code == 403


def test_plain_soldier_can_list_locations(client: TestClient, admin_session: Session):
    # Homepage duty widget fetches locations the same way it fetches duty-types;
    # any authenticated (password-changed) soldier should be able to read them.
    s = create_soldier(admin_session, personal_number="7800003")
    r = client.get("/api/duty-config/locations", headers=auth_headers(s))
    assert r.status_code == 200


def test_commander_can_list_exemption_types(client: TestClient, admin_session: Session):
    # Reference data is readable by any authenticated user (needed to fill the grant form).
    c = create_soldier(admin_session, personal_number="5100041", role="commander")
    assert (
        client.get("/api/duty-config/exemption-types", headers=auth_headers(c)).status_code == 200
    )


def test_duplicate_name_rejected(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100005", role="admin")
    client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "כפול-א", "score_per_day": "1.00", "is_external": False},
    )
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "כפול-א", "score_per_day": "2.00", "is_external": False},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "name_taken"


def test_set_exemption_duty_types(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100006", role="admin")
    et = client.post(
        "/api/duty-config/exemption-types", headers=auth_headers(admin), json={"name": "פטור-א"}
    ).json()
    dt = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "מטבח-א", "score_per_day": "1.00", "is_external": False},
    ).json()
    r = client.put(
        f"/api/duty-config/exemption-types/{et['id']}/duty-types",
        headers=auth_headers(admin),
        json={"duty_type_ids": [dt["id"]]},
    )
    assert r.status_code == 200
    r2 = client.get(
        f"/api/duty-config/exemption-types/{et['id']}/duty-types", headers=auth_headers(admin)
    )
    assert r2.json() == [dt["id"]]


def test_create_duty_type_with_operational_fields(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200001", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={
            "name": "שמירה-ב",
            "score_per_day": "1.00",
            "contact_name": "יוסי כהן",
            "contact_phone": "050-1234567",
            "start_time": "06:00:00",
            "end_time": "18:00:00",
            "instructions": "להגיע עם נשק",
            "is_external": False,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["contact_name"] == "יוסי כהן"
    assert data["contact_phone"] == "050-1234567"
    assert data["start_time"] == "06:00:00"
    assert data["end_time"] == "18:00:00"
    assert data["instructions"] == "להגיע עם נשק"
    assert data["is_external"] is False


def test_create_duty_type_is_external_required(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200002", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ג", "score_per_day": "1.00"},
    )
    assert r.status_code == 422


def test_create_duty_type_instructions_too_long(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200003", role="admin")
    long_instructions = " ".join(["מילה"] * 301)
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ד", "score_per_day": "1.00", "is_external": False, "instructions": long_instructions},
    )
    assert r.status_code == 422


def test_update_duty_type_operational_fields(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200004", role="admin")
    dt = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ה", "score_per_day": "1.00", "is_external": False},
    ).json()
    r = client.patch(
        f"/api/duty-config/duty-types/{dt['id']}",
        headers=auth_headers(admin),
        json={"contact_name": "דני לוי", "is_external": True},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["contact_name"] == "דני לוי"
    assert data["is_external"] is True


def test_create_and_update_duty_type_requires_weapon_roundtrip(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200005", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-נשק-א", "score_per_day": "1.00", "is_external": False, "requires_weapon": True},
    )
    assert r.status_code == 201, r.text
    dt = r.json()
    assert dt["requires_weapon"] is True

    r2 = client.patch(
        f"/api/duty-config/duty-types/{dt['id']}",
        headers=auth_headers(admin),
        json={"requires_weapon": False},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["requires_weapon"] is False

def test_required_range_type_roundtrips_create_update_and_list(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200007", role="admin")
    created = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={
            "name": "שמירה-מטווח-א",
            "score_per_day": "1.00",
            "is_external": False,
            "required_range_type": "laser",
        },
    )
    assert created.status_code == 201, created.text
    created_data = created.json()
    assert created_data["required_range_type"] == "laser"

    updated = client.patch(
        f"/api/duty-config/duty-types/{created_data['id']}",
        headers=auth_headers(admin),
        json={"required_range_type": None},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["required_range_type"] is None

    listed = client.get("/api/duty-config/duty-types", headers=auth_headers(admin))
    assert listed.status_code == 200, listed.text
    listed_data = next(d for d in listed.json() if d["id"] == created_data["id"])
    assert listed_data["required_range_type"] is None

def test_required_range_type_rejects_invalid_values_on_create_and_update(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="5200008", role="admin")
    invalid_create = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={
            "name": "שמירה-מטווח-ב",
            "score_per_day": "1.00",
            "is_external": False,
            "required_range_type": "invalid",
        },
    )
    assert invalid_create.status_code == 422

    created = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={
            "name": "שמירה-מטווח-ג",
            "score_per_day": "1.00",
            "is_external": False,
            "required_range_type": "live",
        },
    )
    assert created.status_code == 201, created.text
    invalid_update = client.patch(
        f"/api/duty-config/duty-types/{created.json()['id']}",
        headers=auth_headers(admin),
        json={"required_range_type": "invalid"},
    )
    assert invalid_update.status_code == 422


def test_create_and_update_exemption_type_forbids_weapons_roundtrip(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200006", role="admin")
    r = client.post(
        "/api/duty-config/exemption-types",
        headers=auth_headers(admin),
        json={"name": "פטור-נשק-א", "forbids_weapons": True},
    )
    assert r.status_code == 201, r.text
    et = r.json()
    assert et["forbids_weapons"] is True

    r2 = client.patch(
        f"/api/duty-config/exemption-types/{et['id']}",
        headers=auth_headers(admin),
        json={"forbids_weapons": False},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["forbids_weapons"] is False


def test_update_exemption_type_active_toggle(client: TestClient, admin_session: Session):
    from app.db.models import ExemptionType

    et = ExemptionType(name="route-active-toggle-test")
    admin_session.add(et)
    admin_session.commit()
    admin = create_soldier(admin_session, personal_number="route_active_admin", role="admin")
    admin_session.commit()

    resp = client.patch(
        f"/api/duty-config/exemption-types/{et.id}",
        headers=auth_headers(admin), json={"active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False


def test_disable_exemption_type_endpoint_bulk_revokes(client: TestClient, admin_session: Session):
    from datetime import date, timedelta
    from app.db.models import ExemptionType, SoldierExemption

    et = ExemptionType(name="route-disable-bulk-test")
    admin_session.add(et)
    admin_session.flush()
    s = create_soldier(admin_session, personal_number="route_disable_bulk_1")
    admin_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date.today() - timedelta(days=1), end_date=None,
    ))
    admin_session.commit()
    admin = create_soldier(admin_session, personal_number="route_disable_bulk_admin", role="admin")
    admin_session.commit()

    resp = client.post(
        f"/api/duty-config/exemption-types/{et.id}/disable",
        headers=auth_headers(admin), json={"reason": "לא בשימוש עוד"},
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_count"] == 1
