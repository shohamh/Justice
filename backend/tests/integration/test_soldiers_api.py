from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import TelegramLink
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
    node = create_node(admin_session, level="team", name="dh_200_node")
    cmd = create_soldier(admin_session, personal_number="dh_200_001", role="soldier")
    node.commander_id = cmd.id
    target = create_soldier(admin_session, personal_number="dh_200_002", hierarchy_node_id=node.id)
    admin_session.commit()

    r = client.get(f"/api/soldiers/{target.id}/duty-history", headers=auth_headers(cmd))
    assert r.status_code == 200
