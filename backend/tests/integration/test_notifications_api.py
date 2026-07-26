import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Announcement, Notification, NotificationType
from tests.helpers import auth_headers, create_node, create_soldier


def test_unread_count_zero(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001001")
    headers = auth_headers(s)
    resp = client.get("/api/notifications/unread-count", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_unread_count_after_creating_notification(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001002")
    headers = auth_headers(s)
    n = Notification(soldier_id=s.id, type=NotificationType.announcement, title="Test")
    admin_session.add(n)
    admin_session.commit()
    resp = client.get("/api/notifications/unread-count", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_list_notifications(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001003")
    headers = auth_headers(s)
    n = Notification(soldier_id=s.id, type=NotificationType.swap_accepted, title="Swap OK")
    admin_session.add(n)
    admin_session.commit()
    resp = client.get("/api/notifications", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Swap OK"
    assert data["items"][0]["type"] == "swap_accepted"
    assert data["items"][0]["is_read"] is False


def test_mark_read(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001004")
    headers = auth_headers(s)
    n = Notification(soldier_id=s.id, type=NotificationType.announcement, title="Read me")
    admin_session.add(n)
    admin_session.commit()
    nid = n.id
    resp = client.patch(f"/api/notifications/{nid}/read", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True


def test_mark_all_read(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001005")
    headers = auth_headers(s)
    for i in range(3):
        admin_session.add(Notification(soldier_id=s.id, type=NotificationType.announcement, title=f"N{i}"))
    admin_session.commit()
    resp = client.patch("/api/notifications/read-all", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 3


def test_delete_notification(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001006")
    headers = auth_headers(s)
    n = Notification(soldier_id=s.id, type=NotificationType.announcement, title="Delete me")
    admin_session.add(n)
    admin_session.commit()
    nid = n.id
    resp = client.delete(f"/api/notifications/{nid}", headers=headers)
    assert resp.status_code == 204


def test_preferences_defaults(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001007")
    headers = auth_headers(s)
    resp = client.get("/api/notifications/preferences", headers=headers)
    assert resp.status_code == 200
    prefs = resp.json()
    assert len(prefs) == len(NotificationType)
    for p in prefs:
        assert p["in_app_enabled"] is True
        assert p["push_enabled"] is False
        assert p["email_enabled"] is True


def test_update_preferences(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001008")
    headers = auth_headers(s)
    resp = client.put("/api/notifications/preferences", headers=headers, json={
        "preferences": [{"notification_type": "announcement", "in_app_enabled": False, "push_enabled": True}]
    })
    assert resp.status_code == 200
    updated = {p["notification_type"]: p for p in resp.json()}
    assert updated["announcement"]["in_app_enabled"] is False
    assert updated["announcement"]["push_enabled"] is True


def test_telegram_generate_code(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001009")
    headers = auth_headers(s)
    resp = client.post("/api/telegram/link", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["code"]) == 6
    assert "expires_at" in data


def test_telegram_link_status_unlinked(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001010")
    headers = auth_headers(s)
    resp = client.get("/api/telegram/link/status", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_verified"] is False


def test_telegram_unlink(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001011")
    headers = auth_headers(s)
    resp = client.post("/api/telegram/link", headers=headers)
    assert resp.status_code == 200
    resp2 = client.delete("/api/telegram/link", headers=headers)
    assert resp2.status_code == 204


def test_commander_scopes(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="TestUnit")
    s = create_soldier(admin_session, personal_number="9001012", role="commander")
    headers = auth_headers(s)
    resp = client.post("/api/notifications/commander-scopes", headers=headers, json={
        "hierarchy_node_id": str(node.id)
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["hierarchy_node_id"] == str(node.id)
    resp2 = client.get("/api/notifications/commander-scopes", headers=headers)
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1


def test_admin_can_broadcast_org_wide(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001013", role="admin")
    headers = auth_headers(admin)
    resp = client.post("/api/notifications/announce", headers=headers, json={"title": "hi"})
    assert resp.status_code == 201


def test_non_admin_cannot_broadcast_org_wide(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="UnitA")
    dm = create_soldier(admin_session, personal_number="9001014", role="duty_manager", hierarchy_node_id=unit_a.id)
    headers = auth_headers(dm)
    resp = client.post("/api/notifications/announce", headers=headers, json={"title": "hi"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "org_wide_announcement_requires_admin"


def test_dm_cannot_broadcast_to_out_of_scope_node(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="UnitA2")
    unit_b = create_node(admin_session, level="unit", name="UnitB2")
    dm = create_soldier(admin_session, personal_number="9001015", role="duty_manager", hierarchy_node_id=unit_a.id)
    headers = auth_headers(dm)
    resp = client.post(
        "/api/notifications/announce",
        headers=headers,
        json={"title": "hi", "hierarchy_node_ids": [str(unit_b.id)]},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "hierarchy_node_out_of_scope"


def test_dm_can_broadcast_to_own_scope(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="UnitA3")
    dm = create_soldier(admin_session, personal_number="9001016", role="duty_manager", hierarchy_node_id=unit_a.id)
    headers = auth_headers(dm)
    resp = client.post(
        "/api/notifications/announce",
        headers=headers,
        json={"title": "hi", "hierarchy_node_ids": [str(unit_a.id)]},
    )
    assert resp.status_code == 201


def test_soldier_cannot_broadcast(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="UnitA4")
    s = create_soldier(admin_session, personal_number="9001017", role="soldier", hierarchy_node_id=unit_a.id)
    headers = auth_headers(s)
    resp = client.post(
        "/api/notifications/announce",
        headers=headers,
        json={"title": "hi", "hierarchy_node_ids": [str(unit_a.id)]},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden"


def test_announcement_row_can_be_created_directly(admin_session: Session):
    sender = create_soldier(admin_session, personal_number="9001019", role="admin")
    a = Announcement(sender_id=sender.id, title="Org update", recipient_count=3, type=NotificationType.system_announcement)
    admin_session.add(a)
    admin_session.commit()
    admin_session.refresh(a)
    assert a.id is not None
    assert a.hierarchy_node_ids is None
    assert a.created_at is not None
