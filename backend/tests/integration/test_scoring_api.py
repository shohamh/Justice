from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier


def test_transparency_403_for_plain_soldier_by_default(client: TestClient, admin_session: Session):
    # Default transparency.min_visible_level is "מדור" (not "every_soldier"), so a
    # plain soldier with no command/DM scope has no visibility by default.
    s = create_soldier(admin_session, personal_number="5600001", role="soldier")
    r = client.get("/api/scoring/transparency", headers=auth_headers(s))
    assert r.status_code == 403


def test_transparency_200_when_every_soldier(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting

    s = create_soldier(admin_session, personal_number="5600009", role="soldier")
    set_setting(admin_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["rows"], list)
    assert "can_see_exemption_aggregates" in body


def test_transparency_allowed_for_commander_of_own_subtree(client: TestClient, admin_session: Session):
    # A commander of any node always passes the has_any_visibility endpoint gate,
    # regardless of that node's level — the old visible_commander_levels
    # multiselect no longer governs this (retired by the transparency rework).
    from tests.helpers import create_node

    cmd = create_soldier(admin_session, personal_number="5600030", role="soldier")
    create_node(admin_session, level="team", name="team-incl", commander_id=cmd.id)
    admin_session.commit()

    r = client.get("/api/scoring/transparency", headers=auth_headers(cmd))
    assert r.status_code == 200


def test_transparency_403_for_duty_manager_without_scope(client: TestClient, admin_session: Session):
    # A duty_manager role alone no longer grants visibility — it requires an
    # actual DutyManagerScope row (or the every_soldier setting).
    dm = create_soldier(admin_session, personal_number="5600032", role="duty_manager")

    r = client.get("/api/scoring/transparency", headers=auth_headers(dm))
    assert r.status_code == 403


def test_transparency_allowed_for_duty_manager_with_scope(client: TestClient, admin_session: Session):
    from tests.helpers import create_node

    node = create_node(admin_session, level="team", name="team-dm-scope")
    dm = create_soldier(
        admin_session, personal_number="5600034", role="duty_manager", hierarchy_node_id=node.id
    )

    r = client.get("/api/scoring/transparency", headers=auth_headers(dm))
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

    from app.services.settings_loader import set_setting

    # Widen row-scope visibility so the plain viewer's row isn't filtered out
    # entirely — this test targets exemption redaction, not row-scope gating.
    set_setting(admin_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
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


def test_fairness_components_403_for_plain_soldier_by_default(client: TestClient, admin_session: Session):
    # Same gating as /scoring/transparency: default transparency.min_visible_level
    # is "מדור", so a plain soldier with no command/DM scope has no visibility.
    s = create_soldier(admin_session, personal_number="5600040", role="soldier")
    r = client.get("/api/scoring/fairness-components", headers=auth_headers(s))
    assert r.status_code == 403


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

    from app.services.settings_loader import set_setting

    set_setting(admin_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
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


def test_burden_share_breakdown_403_for_unrelated_plain_soldier(client: TestClient, admin_session: Session):
    a = create_soldier(admin_session, personal_number="5600050", role="soldier")
    b = create_soldier(admin_session, personal_number="5600051", role="soldier")
    r = client.get(f"/api/scoring/soldiers/{b.id}/burden-share-breakdown", headers=auth_headers(a))
    assert r.status_code == 403


def test_burden_share_breakdown_exposes_contributions(client: TestClient, admin_session: Session):
    """The burden-share-breakdown API must expose the per-quarter traceability line
    items (duty spans + manual adjustments) behind each quarter's score."""
    from datetime import date, datetime

    from app.db.models import DutyAssignment, ScoreAdjustment

    s = create_soldier(admin_session, personal_number="5600052", role="soldier")
    s.enrolled_at = date(2026, 1, 1)
    dt = DutyType(name="שמירה-contrib", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="מוצב-contrib")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    # A published past duty in Q2 2026 (direct insert; no future-planning needed).
    admin_session.add(DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 5, 1), end_date=date(2026, 5, 4), status="published",
    ))
    adj = ScoreAdjustment(soldier_id=s.id, delta=Decimal("1.50"), reason="בדיקת מעקב")
    adj.created_at = datetime(2026, 5, 10, 12, 0, 0)
    admin_session.add(adj)
    admin_session.commit()

    r = client.get(f"/api/scoring/soldiers/{s.id}/burden-share-breakdown", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    q2 = next(q for q in body["quarters"] if q["quarter_label"] == "Q2 2026")
    duty_items = [c for c in q2["contributions"] if c["kind"] == "duty"]
    assert len(duty_items) == 1
    assert duty_items[0]["label"] == "שמירה-contrib"
    assert duty_items[0]["days"] == 3
    assert Decimal(duty_items[0]["score"]) == Decimal("3.000")
    adjustments = [c for c in q2["contributions"] if c["kind"] == "adjustment"]
    assert len(adjustments) == 1 and Decimal(adjustments[0]["score"]) == Decimal("1.50")


def test_burden_share_403_for_unrelated_plain_soldier(client: TestClient, admin_session: Session):
    a = create_soldier(admin_session, personal_number="5600060", role="soldier")
    b = create_soldier(admin_session, personal_number="5600061", role="soldier")
    r = client.get(f"/api/scoring/soldiers/{b.id}/burden-share", headers=auth_headers(a))
    assert r.status_code == 403


def test_burden_share_never_exposes_other_soldier_identity(client: TestClient, admin_session: Session):
    """The whole point of this endpoint: a soldier can see their own rank and an
    anonymized peer distribution, but never another soldier's name or id."""
    dt = DutyType(name="שמירה-burden", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    admin_session.flush()

    s = create_soldier(admin_session, personal_number="5600062", role="soldier", full_name="חייל ראשי")
    peer = create_soldier(admin_session, personal_number="5600063", role="soldier", full_name="חייל שכן")
    admin_session.commit()

    r = client.get(f"/api/scoring/soldiers/{s.id}/burden-share", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    raw = r.text
    assert body["has_group"] is True
    assert body["group_size"] == 2
    assert body["rank"] in (1, 2)
    assert peer.full_name not in raw
    assert str(peer.id) not in raw
    assert "soldier_id" not in raw
    assert "full_name" not in raw


def test_burden_share_has_group_false_when_exempt_from_everything(client: TestClient, admin_session: Session):
    from datetime import date

    from app.db.models import ExemptionType, SoldierExemption

    dt = DutyType(name="שמירה-exempt", score_per_day=Decimal("1.00"))
    admin_session.add(dt)
    admin_session.flush()
    etype = ExemptionType(name="פטור-גורף", is_global=True)
    admin_session.add(etype)
    admin_session.flush()

    s = create_soldier(admin_session, personal_number="5600064", role="soldier")
    admin_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=etype.id, start_date=date(2020, 1, 1), end_date=None,
    ))
    admin_session.commit()

    r = client.get(f"/api/scoring/soldiers/{s.id}/burden-share", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert body["has_group"] is False