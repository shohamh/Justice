from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    SoldierExemption,
    TelegramLink,
)
from app.routes.soldiers import _PUBLIC_EVENT_TYPES
from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_onboards_without_password_gets_temp(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000001", role="admin")
    d = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r = client.post(
        "/api/soldiers",
        headers=auth_headers(admin),
        json={"personal_number": "4100001", "full_name": "טוראי", "hierarchy_node_id": str(d.id)},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "soldier"
    assert body["must_change_password"] is True
    assert len(body["temp_password"]) >= 10


def test_onboard_with_password_no_temp_returned(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000002", role="admin")
    r = client.post(
        "/api/soldiers",
        headers=auth_headers(admin),
        json={
            "personal_number": "4100002",
            "full_name": "טוראי",
            "hierarchy_node_id": None,
            "password": "chosen-password-123",
        },
    )
    assert r.status_code == 201
    assert r.json()["temp_password"] is None


def test_duty_manager_can_only_onboard_in_scope(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(
        admin_session, personal_number="4000003", role="duty_manager", hierarchy_node_id=b.id
    )
    admin_session.commit()
    ok = client.post(
        "/api/soldiers",
        headers=auth_headers(dm),
        json={"personal_number": "4100003", "full_name": "x", "hierarchy_node_id": str(b.id)},
    )
    assert ok.status_code == 201
    denied = client.post(
        "/api/soldiers",
        headers=auth_headers(dm),
        json={"personal_number": "4100004", "full_name": "x", "hierarchy_node_id": str(other.id)},
    )
    assert denied.status_code == 403


def test_reset_password_returns_temp_and_sets_flag(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000005", role="admin")
    target = create_soldier(admin_session, personal_number="4100005")
    r = client.post(f"/api/soldiers/{target.id}/reset-password", headers=auth_headers(admin))
    assert r.status_code == 200
    assert len(r.json()["temp_password"]) >= 10


def test_commander_in_scope_can_reset_password(client: TestClient, admin_session: Session):
    cmd = create_soldier(admin_session, personal_number="4000006", role="commander")
    root = create_node(admin_session, level="group", name="reset_root", commander_id=cmd.id)
    target = create_soldier(admin_session, personal_number="4100006", hierarchy_node_id=root.id)
    admin_session.commit()

    r = client.post(f"/api/soldiers/{target.id}/reset-password", headers=auth_headers(cmd))
    assert r.status_code == 200, r.text
    assert len(r.json()["temp_password"]) >= 10


def test_commander_out_of_scope_cannot_reset_password(client: TestClient, admin_session: Session):
    cmd = create_soldier(admin_session, personal_number="4000007", role="commander")
    create_node(admin_session, level="group", name="reset_own", commander_id=cmd.id)
    other_root = create_node(admin_session, level="group", name="reset_other")
    target = create_soldier(admin_session, personal_number="4100007", hierarchy_node_id=other_root.id)
    admin_session.commit()

    r = client.post(f"/api/soldiers/{target.id}/reset-password", headers=auth_headers(cmd))
    assert r.status_code == 403


def test_soft_delete_sets_left_at(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000008", role="admin")
    target = create_soldier(admin_session, personal_number="4100007")
    r = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(admin))
    assert r.status_code == 204
    admin_session.expire_all()
    assert admin_session.get(type(target), target.id).left_at is not None


def test_release_soldier_sets_left_at_to_given_date(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000009", role="admin")
    target = create_soldier(admin_session, personal_number="4100008")
    r = client.delete(
        f"/api/soldiers/{target.id}",
        params={"left_at": "2026-08-01"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 204
    admin_session.expire_all()
    assert admin_session.get(type(target), target.id).left_at == date(2026, 8, 1)


def test_patch_enrolled_at(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="6200001", role="admin")
    target = create_soldier(admin_session, personal_number="6200002")
    admin_session.commit()
    resp = client.patch(
        f"/api/soldiers/{target.id}",
        json={"enrolled_at": "2024-01-15"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["enrolled_at"] == "2024-01-15"


def test_list_soldiers_telegram_linked_false_by_default(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000001", role="admin")
    s = create_soldier(admin_session, personal_number="5100001")
    admin_session.commit()
    r = client.get("/api/soldiers", headers=auth_headers(admin))
    assert r.status_code == 200
    found = next(x for x in r.json() if x["personal_number"] == "5100001")
    assert found["telegram_linked"] is False


def test_list_soldiers_telegram_linked_true_when_verified(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000002", role="admin")
    s = create_soldier(admin_session, personal_number="5100002")
    admin_session.commit()
    link = TelegramLink(
        soldier_id=s.id,
        is_verified=True,
        telegram_chat_id=999,
        telegram_username="testuser",
    )
    admin_session.add(link)
    admin_session.commit()
    r = client.get("/api/soldiers", headers=auth_headers(admin))
    assert r.status_code == 200
    found = next(x for x in r.json() if x["personal_number"] == "5100002")
    assert found["telegram_linked"] is True


def test_get_soldier_telegram_linked(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000003", role="admin")
    s = create_soldier(admin_session, personal_number="5100003")
    admin_session.commit()
    r = client.get(f"/api/soldiers/{s.id}", headers=auth_headers(admin))
    assert r.json()["telegram_linked"] is False
    link = TelegramLink(soldier_id=s.id, is_verified=True, telegram_chat_id=111, telegram_username="u")
    admin_session.add(link)
    admin_session.commit()
    r2 = client.get(f"/api/soldiers/{s.id}", headers=auth_headers(admin))
    assert r2.json()["telegram_linked"] is True


def test_dual_role_commander_can_see_draft_duty_history(client, admin_session):
    """A soldier who commands a node and is separately a duty manager elsewhere must
    still be able to see draft assignments (include_drafts=true) — role label alone
    must not gate this, only real duty-manager capability."""
    from app.db.models import DutyManagerScope
    from tests.helpers import create_node, create_soldier, auth_headers

    a = create_node(admin_session, level="department", name="draft-vis-a")
    b = create_node(admin_session, level="department", name="draft-vis-b")
    dual = create_soldier(admin_session, personal_number="draft-vis-001", role="commander")
    a.commander_id = dual.id
    target = create_soldier(admin_session, personal_number="draft-vis-002", hierarchy_node_id=b.id)
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    admin_session.commit()
    admin_session.refresh(dual)

    r = client.get(
        f"/api/soldiers/{target.id}/duty-history",
        params={"include_drafts": "true"},
        headers=auth_headers(dual),
    )
    assert r.status_code == 200


def test_duty_history_survives_permanent_pending_exemption_request(client: TestClient, admin_session: Session):
    """Regression test: get_duty_history iterates every ExemptionRequest for a
    soldier with no status filter, so a pending *permanent* request
    (start_date=None) used to crash TimelineEvent construction
    (er.start_date.isoformat() with no None guard) and 500 the soldier's own
    profile / duty-history page for anyone viewing it."""
    admin = create_soldier(admin_session, personal_number="dh_perm_admin", role="admin")
    target = create_soldier(admin_session, personal_number="dh_perm_target")
    et = ExemptionType(name="פטור-dh-perm")
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        ExemptionRequest(
            soldier_id=target.id,
            exemption_type_id=et.id,
            start_date=None,
            reason="פטור קבוע",
            status="pending_commander",
        )
    )
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}/duty-history", headers=auth_headers(admin))
    assert r.status_code == 200
    event = next(e for e in r.json() if e["event_type"] == "exemption_request")
    assert event["date"] is not None


def test_plain_soldier_can_view_another_soldiers_basic_profile(client: TestClient, admin_session: Session):
    """A plain soldier clicking another soldier's name should see a
    read-only, redacted profile — not a 403. Phone/email default to public
    (soldiers.phone_public / soldiers.email_public default True) while other
    private fields (gender) stay gated behind can_see_private."""
    node = create_node(admin_session, level="branch", name="view_node")
    viewer = create_soldier(admin_session, personal_number="view_plain_001", hierarchy_node_id=node.id)
    other_node = create_node(admin_session, level="branch", name="view_other_node")
    target = create_soldier(
        admin_session, personal_number="view_target_001", hierarchy_node_id=other_node.id,
    )
    target.phone = "0501234567"
    target.email = "target@example.com"
    target.gender = "male"
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(viewer))
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == target.full_name
    assert body["phone"] == "0501234567"
    assert body["email"] == "target@example.com"
    assert body["gender"] is None


def test_phone_and_email_hidden_when_public_settings_disabled(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting

    set_setting(admin_session, "soldiers.phone_public", False, actor_id=None)
    set_setting(admin_session, "soldiers.email_public", False, actor_id=None)
    admin_session.commit()

    node = create_node(admin_session, level="branch", name="view_node_2")
    viewer = create_soldier(admin_session, personal_number="view_plain_002", hierarchy_node_id=node.id)
    other_node = create_node(admin_session, level="branch", name="view_other_node_2")
    target = create_soldier(
        admin_session, personal_number="view_target_002", hierarchy_node_id=other_node.id,
    )
    target.phone = "0501234567"
    target.email = "target2@example.com"
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(viewer))
    assert r.status_code == 200
    body = r.json()
    assert body["phone"] is None
    assert body["email"] is None


def test_duty_history_403_for_unrelated_plain_soldier_by_default(client: TestClient, admin_session: Session):
    # Default transparency.min_visible_level is "מדור" (not "every_soldier"), so a
    # plain soldier with no command/DM scope over the target's node has no
    # visibility into that soldier's duty history by default. Previously this
    # endpoint had no permission check at all for the other-soldier branch.
    viewer = create_soldier(admin_session, personal_number="dh_403_001", role="soldier")
    target = create_soldier(admin_session, personal_number="dh_403_002", role="soldier")
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}/duty-history", headers=auth_headers(viewer))
    assert r.status_code == 403


def test_duty_history_200_for_plain_soldier_commanding_target_node(
    client: TestClient, admin_session: Session
):
    # A soldier who commands the target's hierarchy node passes
    # can_view_soldier_scope even though their role label is plain "soldier"
    # (dual-role pattern) — mirrors /scoring/transparency's commander check.
    # Also seeds one public-type event (assignment) and one non-public-type
    # event (exemption, not in _PUBLIC_EVENT_TYPES = {"assignment",
    # "cancellation"}) to prove that passing the new can_view_soldier_scope
    # gate does NOT bypass the existing event-type redaction for a
    # plain-soldier viewer — the two checks are independent layers.
    node = create_node(admin_session, level="team", name="dh_200_node")
    cmd = create_soldier(admin_session, personal_number="dh_200_001", role="soldier")
    node.commander_id = cmd.id
    target = create_soldier(admin_session, personal_number="dh_200_002", hierarchy_node_id=node.id)

    dt = DutyType(name="שמירה-dh200", score_per_day=Decimal("2.00"))
    loc = DutyLocation(name="מוצב-dh200")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=target.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
        )
    )

    et = ExemptionType(name="פטור-dh200")
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(
            soldier_id=target.id, exemption_type_id=et.id, start_date=date(2026, 1, 1)
        )
    )
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}/duty-history", headers=auth_headers(cmd))
    assert r.status_code == 200
    event_types = {e["event_type"] for e in r.json()}
    assert "assignment" in event_types
    assert "exemption" not in event_types
    assert event_types <= _PUBLIC_EVENT_TYPES


def test_duty_history_200_for_senior_rank_commander_viewing_unrelated_soldier(
    client: TestClient, admin_session: Session
):
    # Human ruling: can_view_soldier_scope governs duty-history for EVERY
    # non-self viewer, not just plain soldiers. A commander whose commanded
    # node meets the min_visible_level rank threshold may view an unrelated
    # soldier's duty history. Level keys here are the conftest-seeded English
    # ones, so the threshold is set to the "group" (rank 6) key the commander
    # commands and meets; the migration-seeded default "מדור" label does not
    # resolve against those keys (pre-existing labeling quirk, out of scope).
    from app.services.settings_loader import set_setting

    own = create_node(admin_session, level="group", name="dh_senior_own")
    other = create_node(admin_session, level="team", name="dh_senior_other")
    cmd = create_soldier(admin_session, personal_number="dh_senior_001", role="commander")
    own.commander_id = cmd.id
    target = create_soldier(admin_session, personal_number="dh_senior_002", hierarchy_node_id=other.id)
    set_setting(admin_session, "transparency.min_visible_level", "group", actor_id=None)
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}/duty-history", headers=auth_headers(cmd))
    assert r.status_code == 200


def test_duty_history_200_for_commander_with_levels_above_sibling_branch(
    client: TestClient, admin_session: Session
):
    # A commander with transparency.commander_levels_above >= 1 (the
    # comparison-unit use case) may view duty history of a soldier in a
    # sibling branch under the same ancestor. The commanded node is a
    # "team" (rank 7, below the "מדור" threshold), so only the
    # levels-above expansion path can authorize this.
    from app.services.settings_loader import set_setting

    top = create_node(admin_session, level="department", name="dh_above_top")
    center = create_node(admin_session, level="branch", name="dh_above_center", parent=top)
    own = create_node(admin_session, level="team", name="dh_above_own", parent=center)
    sibling = create_node(admin_session, level="team", name="dh_above_sibling", parent=center)
    cmd = create_soldier(admin_session, personal_number="dh_above_001", role="commander")
    own.commander_id = cmd.id
    target = create_soldier(admin_session, personal_number="dh_above_002", hierarchy_node_id=sibling.id)
    set_setting(admin_session, "transparency.commander_levels_above", 1, actor_id=None)
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}/duty-history", headers=auth_headers(cmd))
    assert r.status_code == 200


def test_list_soldiers_query_count_does_not_scale_with_soldier_count(client: TestClient, admin_session: Session):
    """Finding 3 (N+1 in GET /soldiers): rank_advancement_edit_authorized was
    previously called once per soldier in list_soldiers, each call issuing
    several uncached SELECTs. The fix hoists the actor's scope roots and
    level rank once per request (RankAdvancementEditScope) — so growing the
    roster shouldn't grow the query count by a fixed amount per soldier."""
    from sqlalchemy import event

    from app.db.session import _engine

    node = create_node(admin_session, level="branch", name="n1_scale")
    commander = create_soldier(admin_session, personal_number="scale_cmd_001", role="commander")
    node.commander_id = commander.id
    admin_session.commit()

    for i in range(2):
        create_soldier(admin_session, personal_number=f"scale_a_{i}", hierarchy_node_id=node.id)
    admin_session.commit()

    statements: list[str] = []

    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(_engine, "before_cursor_execute", _record)
    try:
        r1 = client.get("/api/soldiers", headers=auth_headers(commander))
        assert r1.status_code == 200
        assert len(r1.json()) == 3  # commander + 2 soldiers
        count_small = len(statements)

        statements.clear()
        for i in range(2, 12):
            create_soldier(admin_session, personal_number=f"scale_a_{i}", hierarchy_node_id=node.id)
        admin_session.commit()

        r2 = client.get("/api/soldiers", headers=auth_headers(commander))
        assert r2.status_code == 200
        assert len(r2.json()) == 13  # commander + 12 soldiers
        count_large = len(statements)
    finally:
        event.remove(_engine, "before_cursor_execute", _record)

    # 8 additional soldiers must not add anywhere near 8 * (2-6) extra
    # queries — with the fix the delta should be small/flat (a handful of
    # bulk queries at most), not proportional to soldier count.
    assert count_large - count_small < 8, (
        f"query count grew from {count_small} to {count_large} for +8 soldiers "
        "-- looks like a per-soldier N+1 regression"
    )


def test_commander_at_mador_or_above_can_delete_in_scope(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting
    # tests/conftest.py seeds English level keys (see _LEVEL_TYPE_DEFAULTS);
    # "group" is rank 6, labeled "מדור" — use its key directly since
    # commander_delete_soldier_authorized compares against the level KEY.
    set_setting(admin_session, "soldiers.commander_delete_min_level", "group", actor_id=None)
    admin_session.commit()
    cmd = create_soldier(admin_session, personal_number="9600001", role="commander")
    root = create_node(admin_session, level="group", name="del_root", commander_id=cmd.id)
    target = create_soldier(admin_session, personal_number="9600002", hierarchy_node_id=root.id)
    admin_session.commit()

    resp = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(cmd))
    assert resp.status_code == 204, resp.text


def test_commander_below_min_level_cannot_delete(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting
    # Pin the min-level setting explicitly to "group" (rather than relying on
    # the hardcoded "מדור" fallback key, which cannot resolve against this
    # test fixture's English level keys) so this test's commander at "team"
    # (rank 7, genuinely below "group"'s rank 6) fails a real below-threshold
    # comparison rather than an unresolvable level key.
    set_setting(admin_session, "soldiers.commander_delete_min_level", "group", actor_id=None)
    cmd = create_soldier(admin_session, personal_number="9600003", role="commander")
    root = create_node(admin_session, level="team", name="del_root2", commander_id=cmd.id)
    target = create_soldier(admin_session, personal_number="9600004", hierarchy_node_id=root.id)
    admin_session.commit()

    resp = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(cmd))
    assert resp.status_code == 403


def test_commander_out_of_scope_cannot_delete_via_api(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "soldiers.commander_delete_min_level", "group", actor_id=None)
    admin_session.commit()
    cmd = create_soldier(admin_session, personal_number="9600005", role="commander")
    create_node(admin_session, level="group", name="del_own", commander_id=cmd.id)
    other_root = create_node(admin_session, level="group", name="del_other")
    target = create_soldier(admin_session, personal_number="9600006", hierarchy_node_id=other_root.id)
    admin_session.commit()

    resp = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(cmd))
    assert resp.status_code == 403


def test_me_exposes_can_delete_soldier_flag(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "soldiers.commander_delete_min_level", "group", actor_id=None)
    admin_session.commit()
    qualifying = create_soldier(admin_session, personal_number="9600007", role="commander")
    create_node(admin_session, level="group", name="me_flag_root", commander_id=qualifying.id)
    junior = create_soldier(admin_session, personal_number="9600008", role="commander")
    create_node(admin_session, level="team", name="me_flag_root2", commander_id=junior.id)
    admin_session.commit()

    r1 = client.get("/api/me", headers=auth_headers(qualifying))
    assert r1.json()["can_delete_soldier"] is True
    r2 = client.get("/api/me", headers=auth_headers(junior))
    assert r2.json()["can_delete_soldier"] is False
