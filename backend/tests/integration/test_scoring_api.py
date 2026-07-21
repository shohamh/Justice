from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier


def test_transparency_open_to_any_authed_user(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5600001", role="soldier")
    r = client.get("/api/scoring/transparency", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["rows"], list)
    assert "can_see_exemption_aggregates" in body


def test_transparency_denied_for_commander_at_excluded_level(client: TestClient, admin_session: Session):
    from tests.helpers import create_node
    from app.services.settings_loader import set_setting

    cmd = create_soldier(admin_session, personal_number="5600030", role="soldier")
    create_node(admin_session, level="team", name="team-excl", commander_id=cmd.id)
    set_setting(admin_session, "transparency.visible_commander_levels", ["brigade"], actor_id=None)
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(cmd))
    assert r.status_code == 403


def test_transparency_allowed_for_commander_at_included_level(client: TestClient, admin_session: Session):
    from tests.helpers import create_node
    from app.services.settings_loader import set_setting

    cmd = create_soldier(admin_session, personal_number="5600031", role="soldier")
    create_node(admin_session, level="team", name="team-incl", commander_id=cmd.id)
    set_setting(admin_session, "transparency.visible_commander_levels", ["team", "branch"], actor_id=None)
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(cmd))
    assert r.status_code == 200


def test_transparency_allowed_for_duty_manager_regardless_of_level(
    client: TestClient, admin_session: Session
):
    from app.services.settings_loader import set_setting

    dm = create_soldier(admin_session, personal_number="5600032", role="duty_manager")
    set_setting(admin_session, "transparency.visible_commander_levels", ["team"], actor_id=None)
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(dm))
    assert r.status_code == 200


def test_transparency_allowed_by_default(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5600033", role="soldier")
    r = client.get("/api/scoring/transparency", headers=auth_headers(s))
    assert r.status_code == 200


def test_transparency_reflects_assignment(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5600002", role="admin")
    s = create_soldier(admin_session, personal_number="5600003", role="soldier")
    dt = DutyType(name="שמירה-sca", score_per_day=Decimal("2.00"))
    loc = DutyLocation(name="מוצב-sca")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={
            "soldier_id": str(s.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
        },
    )
    r = client.get("/api/scoring/transparency", headers=auth_headers(admin))
    row = next(x for x in r.json()["rows"] if x["soldier_id"] == str(s.id))
    assert Decimal(row["cumulative_score"]) == Decimal("4.00")


def test_transparency_exemptions_redacted_for_plain_soldier(client: TestClient, admin_session: Session):
    from datetime import date

    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-api-redact")
    viewer = create_soldier(admin_session, personal_number="5600007", role="soldier")
    target = create_soldier(admin_session, personal_number="5600008", hierarchy_node_id=node.id)
    et = ExemptionType(name="שחרור", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=target.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(viewer))
    body = r.json()
    assert body["can_see_exemption_aggregates"] is False
    row = next(x for x in body["rows"] if x["soldier_id"] == str(target.id))
    assert row["exemptions_display"] == "חסוי"
    assert row["has_global_exemption"] is None


def test_soldier_can_read_own_breakdown(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5600004", role="soldier")
    r = client.get(f"/api/scoring/soldiers/{s.id}", headers=auth_headers(s))
    assert r.status_code == 200
    assert "per_type" in r.json()


def test_soldier_cannot_read_other_breakdown(client: TestClient, admin_session: Session):
    a = create_soldier(admin_session, personal_number="5600005", role="soldier")
    b = create_soldier(admin_session, personal_number="5600006", role="soldier")
    r = client.get(f"/api/scoring/soldiers/{b.id}", headers=auth_headers(a))
    assert r.status_code == 403


def test_transparency_exemptions_array_populated_in_scope(client: TestClient, admin_session: Session):
    from datetime import date

    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-api-exarr")
    cmd = create_soldier(admin_session, personal_number="5600020", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5600021", hierarchy_node_id=node.id)
    et = ExemptionType(name="פטור-מערך1", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    ex = SoldierExemption(
        soldier_id=target.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )
    admin_session.add(ex)
    admin_session.commit()
    admin_session.refresh(ex)

    r = client.get("/api/scoring/transparency", headers=auth_headers(cmd))
    row = next(x for x in r.json()["rows"] if x["soldier_id"] == str(target.id))
    assert row["exemptions_visible"] is True
    assert len(row["exemptions"]) == 1
    item = row["exemptions"][0]
    assert item["id"] == str(ex.id)
    assert item["exemption_type_name"] == "פטור-מערך1"
    assert item["is_global"] is True
    assert item["start_date"] == "2026-01-01"
    assert item["end_date"] == "2026-12-31"


def test_transparency_exemptions_array_empty_when_redacted(client: TestClient, admin_session: Session):
    from datetime import date

    from app.db.models import ExemptionType, SoldierExemption
    from tests.helpers import create_node

    node = create_node(admin_session, level="division", name="div-api-exarr2")
    viewer = create_soldier(admin_session, personal_number="5600022", role="soldier")
    target = create_soldier(admin_session, personal_number="5600023", hierarchy_node_id=node.id)
    et = ExemptionType(name="פטור-מערך2", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=target.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(viewer))
    row = next(x for x in r.json()["rows"] if x["soldier_id"] == str(target.id))
    assert row["exemptions_visible"] is False
    assert row["exemptions"] == []
