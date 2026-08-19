import json
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExemptionRequest, ExemptionType, SoldierExemption
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session, name):
    et = ExemptionType(name=name)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


def test_commander_grants_in_subtree(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="5200001", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5200002", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-ר1")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "גב"},
    )
    assert r.status_code == 201, r.text
    r2 = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(cmd))
    assert len(r2.json()) == 1


def test_commander_out_of_subtree_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="5200003", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5200004", hierarchy_node_id=other.id)
    et = _et(admin_session, "פטור-ר2")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    assert r.status_code == 403


def test_soldier_reads_own_but_cannot_grant(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5200005", role="soldier")
    et = _et(admin_session, "פטור-ר3")
    r = client.get(f"/api/soldiers/{s.id}/exemptions", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json() == []
    r2 = client.post(
        f"/api/soldiers/{s.id}/exemptions",
        headers=auth_headers(s),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    assert r2.status_code == 403


def test_revoke_active_soft(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200006", role="admin")
    target = create_soldier(admin_session, personal_number="5200007")
    et = _et(admin_session, "פטור-ר4")
    ex = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(admin),
        json={
            "exemption_type_id": str(et.id),
            "start_date": (date.today() - timedelta(days=2)).isoformat(),
        },
    ).json()
    r = client.request(
        "DELETE",
        f"/api/soldiers/{target.id}/exemptions/{ex['id']}",
        headers=auth_headers(admin),
        json={"reason": "לא נחוץ יותר"},
    )
    assert r.status_code == 204
    rows = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin)).json()
    assert rows[0]["end_date"] == date.today().isoformat()


def test_revoke_rejects_cross_soldier_id(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200008", role="admin")
    a = create_soldier(admin_session, personal_number="5200009")
    b = create_soldier(admin_session, personal_number="5200010")
    et = _et(admin_session, "פטור-ר5")
    ex = client.post(
        f"/api/soldiers/{a.id}/exemptions",
        headers=auth_headers(admin),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    ).json()
    r = client.request(
        "DELETE",
        f"/api/soldiers/{b.id}/exemptions/{ex['id']}",
        headers=auth_headers(admin),
        json={"reason": "לא רלוונטי"},
    )
    assert r.status_code == 404


def test_patch_pending_commander_request_succeeds(client: TestClient, admin_session: Session):
    """Regression test: the PATCH route's pending-status check still referenced the
    single old "pending" status after it was split into pending_commander/pending_duty_manager,
    which made this endpoint unconditionally reject every request. Confirms it now accepts
    a request in either new pending sub-state."""
    admin = create_soldier(admin_session, personal_number="5200011", role="admin")
    soldier = create_soldier(admin_session, personal_number="5200012")
    et = _et(admin_session, "פטור-ר6")
    req = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(soldier),
        data={"payload": json.dumps({"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "בדיקה"})},
        files=[],
    ).json()
    assert req["status"] == "pending_commander"
    r = client.patch(
        f"/api/exemption-requests/{req['id']}",
        headers=auth_headers(admin),
        json={"reason": "updated reason"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_commander"


def test_patch_rejects_retargeting_to_commander_exemption_type(client: TestClient, admin_session: Session):
    """A pending request's exemption_type_id must not be retargeted to a
    commander-exemption type — that would bypass the rank/level gate that
    grant_commander_exemption otherwise enforces."""
    admin = create_soldier(admin_session, personal_number="5200013", role="admin")
    soldier = create_soldier(admin_session, personal_number="5200014")
    regular = _et(admin_session, "פטור-ר7")
    commander_et = ExemptionType(name="פטור-פיקודי-ר7", is_commander_exemption=True)
    admin_session.add(commander_et)
    admin_session.commit()
    req = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(soldier),
        data={"payload": json.dumps({"exemption_type_id": str(regular.id), "start_date": "2026-01-01", "reason": "בדיקה"})},
        files=[],
    ).json()
    r = client.patch(
        f"/api/exemption-requests/{req['id']}",
        headers=auth_headers(admin),
        json={"exemption_type_id": str(commander_et.id)},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "commander_exemption_not_requestable"


def test_patch_rejects_setting_end_date_without_start_date(client: TestClient, admin_session: Session):
    """The PATCH route lets an approver set start_date/end_date independently.
    Setting only end_date on a permanent (start_date=None) request would
    produce the one state the rest of the system forbids
    (start_date=None, end_date=<date>), which later crashes
    _format_exemption_period when the request is rejected. Must be blocked
    up front instead."""
    admin = create_soldier(admin_session, personal_number="5200015", role="admin")
    soldier = create_soldier(admin_session, personal_number="5200016")
    et = _et(admin_session, "פטור-ר8")
    req = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(soldier),
        data={"payload": json.dumps({
            "exemption_type_id": str(et.id), "start_date": None, "end_date": None, "reason": "פטור קבוע",
        })},
        files=[],
    ).json()
    assert req["start_date"] is None

    r = client.patch(
        f"/api/exemption-requests/{req['id']}",
        headers=auth_headers(admin),
        json={"end_date": "2026-06-01"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "start_date_required"


def test_reject_permanent_start_date_pending_request_does_not_crash(client: TestClient, admin_session: Session):
    """A permanent exemption request (start_date=None, end_date=None) must be
    rejectable without _format_exemption_period crashing on a None start_date."""
    admin = create_soldier(admin_session, personal_number="5200017", role="admin")
    soldier = create_soldier(admin_session, personal_number="5200018")
    et = _et(admin_session, "פטור-ר9")
    req = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(soldier),
        data={"payload": json.dumps({
            "exemption_type_id": str(et.id), "start_date": None, "end_date": None, "reason": "פטור קבוע",
        })},
        files=[],
    ).json()

    r = client.post(
        f"/api/exemption-requests/{req['id']}/reject",
        headers=auth_headers(admin),
        json={"decision_note": "לא רלוונטי"},
    )
    assert r.status_code == 200, r.text


def test_detail_endpoint_shows_reason_when_authorized(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-detail1")
    b = create_node(admin_session, level="branch", name="b-detail1", parent=d)
    cmd = create_soldier(admin_session, personal_number="5200020", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5200021", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-דטייל1")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "end_date": "2026-06-01", "reason": "בעיה רפואית"},
    )
    exemption_id = r.json()["id"]

    r2 = client.get(f"/api/soldiers/{target.id}/exemptions/{exemption_id}", headers=auth_headers(cmd))
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["exemption_type_name"] == "פטור-דטייל1"
    assert body["is_global"] is False
    assert body["start_date"] == "2026-01-01"
    assert body["end_date"] == "2026-06-01"
    assert body["reason"] == "בעיה רפואית"
    assert body["granted_by_name"] == cmd.full_name


def test_detail_endpoint_hides_reason_when_not_private(client: TestClient, admin_session: Session):
    """A plain admin (not also a commander/duty-manager) passes EXEMPTION_READ
    unconditionally (authz.can(): `if user.role == "admin": return True`), but
    can_see_private_node() deliberately does NOT grant admins a bypass — it
    requires is_commander or is_duty_manager. So a plain admin is exactly the
    "can read, cannot see private fields" case: reason must come back None."""
    node = create_node(admin_session, level="department", name="d-detail2")
    admin_grantor = create_soldier(admin_session, personal_number="5200022", role="admin")
    target = create_soldier(admin_session, personal_number="5200023", hierarchy_node_id=node.id)
    et = _et(admin_session, "פטור-דטייל2")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(admin_grantor),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "סודי"},
    )
    exemption_id = r.json()["id"]

    viewer_admin = create_soldier(admin_session, personal_number="5200024", role="admin")
    r2 = client.get(f"/api/soldiers/{target.id}/exemptions/{exemption_id}", headers=auth_headers(viewer_admin))
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["reason"] is None
    assert body["exemption_type_name"] == "פטור-דטייל2"  # non-private fields still shown


def test_detail_endpoint_404_for_mismatched_soldier(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200027", role="admin")
    s1 = create_soldier(admin_session, personal_number="5200028", role="soldier")
    s2 = create_soldier(admin_session, personal_number="5200029", role="soldier")
    et = _et(admin_session, "פטור-דטייל4")
    r = client.post(
        f"/api/soldiers/{s1.id}/exemptions",
        headers=auth_headers(admin),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    exemption_id = r.json()["id"]
    r2 = client.get(f"/api/soldiers/{s2.id}/exemptions/{exemption_id}", headers=auth_headers(admin))
    assert r2.status_code == 404


def test_detail_endpoint_403_when_not_authorized(client: TestClient, admin_session: Session):
    """A plain soldier (no admin/commander/duty-manager role) has no
    EXEMPTION_READ path to another soldier's exemption — authorize() must
    reject before any data is returned. This pins the detail endpoint's core
    defense-in-depth guarantee: it re-authorizes independently, rather than
    trusting whatever gated the bulk list endpoints (Transparency/Potential)."""
    node = create_node(admin_session, level="department", name="d-detail5")
    admin = create_soldier(admin_session, personal_number="5200030", role="admin")
    target = create_soldier(admin_session, personal_number="5200031", hierarchy_node_id=node.id)
    et = _et(admin_session, "פטור-דטייל5")
    r = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(admin),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01"},
    )
    exemption_id = r.json()["id"]

    viewer = create_soldier(admin_session, personal_number="5200032", role="soldier")
    r2 = client.get(f"/api/soldiers/{target.id}/exemptions/{exemption_id}", headers=auth_headers(viewer))
    assert r2.status_code == 403


def test_revoke_requires_reason_body(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200015", role="admin")
    target = create_soldier(admin_session, personal_number="5200016")
    et = _et(admin_session, "פטור-ר8")
    ex = client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(admin),
        json={
            "exemption_type_id": str(et.id),
            "start_date": (date.today() - timedelta(days=1)).isoformat(),
        },
    ).json()

    resp = client.request(
        "DELETE",
        f"/api/soldiers/{target.id}/exemptions/{ex['id']}",
        headers=auth_headers(admin),
        json={},
    )
    assert resp.status_code == 422  # missing required "reason"

    resp2 = client.request(
        "DELETE",
        f"/api/soldiers/{target.id}/exemptions/{ex['id']}",
        headers=auth_headers(admin),
        json={"reason": "בדיקת מסלול"},
    )
    assert resp2.status_code == 204


def test_exemption_out_hides_revoke_reason_from_out_of_scope_viewer(
    client: TestClient, admin_session: Session
):
    # An admin who is *not* a commander/duty-manager over the target's node
    # passes the EXEMPTION_READ authorization check (admins always can), but
    # must not see private fields like revoke_reason/revoked_by_name per
    # can_see_private's explicit no-blanket-bypass-for-admins rule.
    d = create_node(admin_session, level="department", name="d-revoke")
    b = create_node(admin_session, level="branch", name="b-revoke", parent=d)
    target = create_soldier(admin_session, personal_number="5200017", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-ר9")
    admin_session.add(
        SoldierExemption(
            soldier_id=target.id,
            exemption_type_id=et.id,
            start_date=date.today(),
            end_date=date.today(),
            revoked_at=datetime.now(timezone.utc),
            revoke_reason="פרטי",
        )
    )
    admin_session.commit()

    other_admin = create_soldier(admin_session, personal_number="5200018", role="admin")

    resp = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(other_admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["revoke_reason"] is None
    assert body[0]["revoked_by_name"] is None


def test_detail_endpoint_hides_revoke_reason_from_out_of_scope_viewer(
    client: TestClient, admin_session: Session
):
    d = create_node(admin_session, level="department", name="d-detail-revoke")
    b = create_node(admin_session, level="branch", name="b-detail-revoke", parent=d)
    target = create_soldier(admin_session, personal_number="5200019", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-דטייל-ר1")
    admin_session.add(
        SoldierExemption(
            soldier_id=target.id,
            exemption_type_id=et.id,
            start_date=date.today(),
            end_date=date.today(),
            revoked_at=datetime.now(timezone.utc),
            revoke_reason="פרטי דטייל",
        )
    )
    admin_session.commit()
    exemption_id = admin_session.execute(
        select(SoldierExemption.id).where(SoldierExemption.soldier_id == target.id)
    ).scalar_one()

    other_admin = create_soldier(admin_session, personal_number="5200020b", role="admin")

    resp = client.get(
        f"/api/soldiers/{target.id}/exemptions/{exemption_id}", headers=auth_headers(other_admin)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["revoke_reason"] is None
    assert body["revoked_by_name"] is None


def test_exemption_request_includes_nearest_commander_and_duty_manager(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-nearest-exreq")
    b = create_node(admin_session, level="branch", name="b-nearest-exreq", parent=d)
    cmd = create_soldier(admin_session, personal_number="5200040", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    dm = create_soldier(admin_session, personal_number="5200041", role="duty_manager", hierarchy_node_id=d.id)
    soldier = create_soldier(admin_session, personal_number="5200042", hierarchy_node_id=b.id)
    et = _et(admin_session, "פטור-נראסט")
    req = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(soldier),
        data={"payload": json.dumps({"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "בדיקה"})},
        files=[],
    ).json()
    assert req["nearest_commander"]["id"] == str(cmd.id)
    assert req["nearest_commander"]["name"] == cmd.full_name
    assert req["nearest_duty_manager"]["id"] == str(dm.id)
    assert req["nearest_duty_manager"]["name"] == dm.full_name

    r2 = client.get("/api/me/exemption-requests", headers=auth_headers(soldier))
    items = r2.json()
    assert len(items) == 1
    assert items[0]["nearest_commander"]["id"] == str(cmd.id)
    assert items[0]["nearest_duty_manager"]["id"] == str(dm.id)


def test_upload_exemption_file_rejects_content_type_mismatch(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="mb_soldier_001")
    et = ExemptionType(name="mb-type-001", is_medical=True)
    admin_session.add(et)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, status="draft", start_date=date(2026, 1, 1),
    )
    admin_session.add(req)
    admin_session.commit()

    r = client.post(
        f"/api/me/exemption-requests/{req.id}/files",
        files={"file": ("fake.png", b"<script>alert(1)</script>", "image/png")},
        headers=auth_headers(soldier),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_file_type"


def test_pending_exemption_flags_dm_below_minimum_level_as_unable_to_approve(client, admin_session):
    from app.db.models import HierarchyLevelType
    from sqlalchemy import delete
    admin_session.execute(delete(HierarchyLevelType))
    admin_session.flush()
    admin_session.add_all([
        HierarchyLevelType(key="מרכז", label="מרכז", rank=1),
        HierarchyLevelType(key="מדור", label="מדור", rank=2),
    ])
    admin_session.commit()

    mador = create_node(admin_session, level="מדור", name="ex_flag_mador")
    dm = create_soldier(admin_session, personal_number="ex_flag_dm", role="duty_manager", hierarchy_node_id=mador.id)
    soldier = create_soldier(admin_session, personal_number="ex_flag_sol", hierarchy_node_id=mador.id)
    admin_session.commit()

    et = ExemptionType(name="ex-flag-type", is_medical=False)
    admin_session.add(et)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, status="pending_duty_manager", start_date=date(2026, 1, 1),
    )
    admin_session.add(req)
    admin_session.commit()

    r = client.get("/api/exemption-requests/pending", headers=auth_headers(dm))
    assert r.status_code == 200
    items = [i for i in r.json() if i["id"] == str(req.id)]
    assert len(items) == 1
    assert items[0]["can_approve_duty_manager_step"] is False


def test_pending_exemption_count_excludes_requests_dm_below_minimum_level_cannot_approve(client, admin_session):
    """The count feeds the commander/approvals nav badge — it must match
    can_approve_duty_manager_step, not mere read-visibility (see the sibling
    can_approve_duty_manager_step test above using the same scenario)."""
    from app.db.models import HierarchyLevelType
    from sqlalchemy import delete
    admin_session.execute(delete(HierarchyLevelType))
    admin_session.flush()
    admin_session.add_all([
        HierarchyLevelType(key="מרכז", label="מרכז", rank=1),
        HierarchyLevelType(key="מדור", label="מדור", rank=2),
    ])
    admin_session.commit()

    mador = create_node(admin_session, level="מדור", name="ex_count_mador")
    dm = create_soldier(admin_session, personal_number="ex_count_dm", role="duty_manager", hierarchy_node_id=mador.id)
    soldier = create_soldier(admin_session, personal_number="ex_count_sol", hierarchy_node_id=mador.id)
    admin_session.commit()

    et = ExemptionType(name="ex-count-type", is_medical=False)
    admin_session.add(et)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, status="pending_duty_manager", start_date=date(2026, 1, 1),
    )
    admin_session.add(req)
    admin_session.commit()

    r = client.get("/api/exemption-requests/pending/count", headers=auth_headers(dm))
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_plain_commander_cannot_use_direct_commander_exemption_route(client: TestClient, admin_session: Session):
    from app.db.models import ExemptionType
    from app.services.settings_loader import set_setting
    # Pin the base commander-exemption-grant min-level setting to this test's
    # own level ("group") so the commander would have passed the OLD
    # commander_can_grant_commander_exemption gate — otherwise, with no
    # setting row seeded, the hardcoded fallback key "מדור" cannot resolve
    # against this test's "group" level and the 403 is unattributable to the
    # removed commander branch (see comment in
    # test_dm_at_merkaz_can_use_direct_commander_exemption_route below).
    set_setting(admin_session, "exemptions.commander_exemption_min_level", "group", actor_id=None)
    et = ExemptionType(name="פטור-ישיר-1", is_commander_exemption=True)
    admin_session.add(et)
    admin_session.commit()
    admin_session.refresh(et)
    cmd = create_soldier(admin_session, personal_number="9900001", role="commander")
    root = create_node(admin_session, level="group", name="direct_grant_root", commander_id=cmd.id)
    target = create_soldier(admin_session, personal_number="9900002", hierarchy_node_id=root.id)
    admin_session.commit()

    resp = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-exemption",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "x"},
    )
    assert resp.status_code == 403


def test_dm_at_merkaz_can_use_direct_commander_exemption_route(client: TestClient, admin_session: Session):
    from app.db.models import DutyManagerScope, ExemptionType
    from app.services.settings_loader import set_setting
    et = ExemptionType(name="פטור-ישיר-2", is_commander_exemption=True)
    admin_session.add(et)
    admin_session.commit()
    admin_session.refresh(et)
    # The default hierarchy levels seeded for tests use English keys ("department")
    # with Hebrew labels ("מרכז") — the fallback default of the min-level setting is
    # the Hebrew label, which never matches a key, so pin the setting explicitly to
    # the key that matches the level used below (mirrors the pattern established by
    # the commander-delete-gate tests in test_soldiers_api.py).
    set_setting(admin_session, "exemptions.commander_escalation_min_level", "department", actor_id=None)
    dm = create_soldier(admin_session, personal_number="9900003", role="duty_manager")
    root = create_node(admin_session, level="department", name="direct_grant_root2")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=root.id))
    target = create_soldier(admin_session, personal_number="9900004", hierarchy_node_id=root.id)
    admin_session.commit()

    resp = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-exemption",
        headers=auth_headers(dm),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "x"},
    )
    assert resp.status_code == 201, resp.text
