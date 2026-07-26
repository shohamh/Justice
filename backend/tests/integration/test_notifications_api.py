import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Announcement, CommanderNotificationScope, HierarchyNode, Notification, NotificationType
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


def test_read_at_set_on_mark_read(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="9001018")
    headers = auth_headers(s)
    n = Notification(soldier_id=s.id, type=NotificationType.announcement, title="Read me too")
    admin_session.add(n)
    admin_session.commit()
    nid = n.id
    resp = client.patch(f"/api/notifications/{nid}/read", headers=headers)
    assert resp.status_code == 200
    admin_session.refresh(n)
    assert n.read_at is not None


def test_broadcast_org_wide_uses_system_announcement_type(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001020", role="admin")
    headers = auth_headers(admin)
    recipient = create_soldier(admin_session, personal_number="9001021")
    resp = client.post("/api/notifications/announce", headers=headers, json={"title": "org wide"})
    assert resp.status_code == 201
    notif = admin_session.execute(
        select(Notification).where(Notification.soldier_id == recipient.id, Notification.title == "org wide")
    ).scalar_one()
    assert notif.type == NotificationType.system_announcement
    assert notif.reference_type == "announcement"
    assert notif.reference_id == uuid.UUID(resp.json()["id"])


def test_broadcast_scoped_uses_announcement_type(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="UnitScopeType")
    dm = create_soldier(admin_session, personal_number="9001022", role="duty_manager", hierarchy_node_id=unit_a.id)
    recipient = create_soldier(admin_session, personal_number="9001023", hierarchy_node_id=unit_a.id)
    headers = auth_headers(dm)
    resp = client.post(
        "/api/notifications/announce", headers=headers,
        json={"title": "scoped", "hierarchy_node_ids": [str(unit_a.id)]},
    )
    assert resp.status_code == 201
    notif = admin_session.execute(
        select(Notification).where(Notification.soldier_id == recipient.id, Notification.title == "scoped")
    ).scalar_one()
    assert notif.type == NotificationType.announcement


def test_admin_scoped_announcement_still_uses_scoped_type(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="UnitAdminScoped")
    admin = create_soldier(admin_session, personal_number="9001024", role="admin")
    recipient = create_soldier(admin_session, personal_number="9001025", hierarchy_node_id=unit_a.id)
    headers = auth_headers(admin)
    resp = client.post(
        "/api/notifications/announce", headers=headers,
        json={"title": "admin scoped", "hierarchy_node_ids": [str(unit_a.id)]},
    )
    assert resp.status_code == 201
    notif = admin_session.execute(
        select(Notification).where(Notification.soldier_id == recipient.id, Notification.title == "admin scoped")
    ).scalar_one()
    assert notif.type == NotificationType.announcement  # scope-driven, not sender-driven


def test_announce_scope_returns_own_roots_for_dm(client: TestClient, admin_session: Session):
    unit_a = create_node(admin_session, level="unit", name="ScopeEndpointUnit")
    dm = create_soldier(admin_session, personal_number="9001026", role="duty_manager", hierarchy_node_id=unit_a.id)
    headers = auth_headers(dm)
    resp = client.get("/api/notifications/announce/scope", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(unit_a.id)
    assert data[0]["name"] == "ScopeEndpointUnit"
    assert data[0]["parent_id"] is None


def test_announce_scope_includes_descendants_for_dm(client: TestClient, admin_session: Session):
    parent = create_node(admin_session, level="company", name="ScopeParentUnit")
    child = create_node(admin_session, level="platoon", name="ScopeChildUnit", parent=parent)
    dm = create_soldier(admin_session, personal_number="9001040", role="duty_manager", hierarchy_node_id=parent.id)
    headers = auth_headers(dm)
    resp = client.get("/api/notifications/announce/scope", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    ids = {row["id"]: row for row in data}
    assert str(parent.id) in ids
    assert str(child.id) in ids
    assert ids[str(parent.id)]["parent_id"] is None
    assert ids[str(child.id)]["parent_id"] == str(parent.id)


def test_announce_scope_empty_for_admin(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001027", role="admin")
    headers = auth_headers(admin)
    resp = client.get("/api/notifications/announce/scope", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_announce_returns_id_and_sent_count(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001028", role="admin")
    create_soldier(admin_session, personal_number="9001029")
    headers = auth_headers(admin)
    resp = client.post("/api/notifications/announce", headers=headers, json={"title": "count me"})
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["sent"] >= 2  # admin + the extra soldier created above (and any others in this test DB)


def test_list_sent_announcements_history(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001030", role="admin")
    headers = auth_headers(admin)
    send_resp = client.post("/api/notifications/announce", headers=headers, json={"title": "history item"})
    announcement_id = send_resp.json()["id"]
    resp = client.get("/api/notifications/announcements", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next(i for i in items if i["id"] == announcement_id)
    assert match["title"] == "history item"
    assert match["read_count"] == 0
    assert match["recipient_count"] >= 1


def test_announcement_recipients_endpoint(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001031", role="admin")
    recipient = create_soldier(admin_session, personal_number="9001032")
    headers = auth_headers(admin)
    send_resp = client.post("/api/notifications/announce", headers=headers, json={"title": "recipients test"})
    announcement_id = send_resp.json()["id"]
    resp = client.get(f"/api/notifications/announcements/{announcement_id}/recipients", headers=headers)
    assert resp.status_code == 200
    rows = resp.json()["items"]
    match = next(r for r in rows if r["soldier_id"] == str(recipient.id))
    assert match["full_name"] == recipient.full_name
    assert match["is_read"] is False
    assert match["read_at"] is None


def test_announcement_recipients_404_for_non_owner(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001033", role="admin")
    other_admin = create_soldier(admin_session, personal_number="9001034", role="admin")
    headers = auth_headers(admin)
    send_resp = client.post("/api/notifications/announce", headers=headers, json={"title": "not yours"})
    announcement_id = send_resp.json()["id"]
    other_headers = auth_headers(other_admin)
    resp = client.get(f"/api/notifications/announcements/{announcement_id}/recipients", headers=other_headers)
    assert resp.status_code == 404


def test_announcement_does_not_duplicate_via_commander_cascade(client: TestClient, admin_session: Session):
    """Regression test for Finding 1/2: broadcast_announcement already includes every
    relevant soldier (commanders included, since they're Soldier rows too) in its
    recipient list. create_notification must NOT also cascade_to_commanders() for
    announcement types, or a commander with a CommanderNotificationScope over the
    recipient's node gets a duplicate Notification row sharing the same
    reference_id — corrupting recipient_count/read_count and the recipient list.
    """
    node = create_node(admin_session, level="unit", name="CascadeTestUnit")
    recipient = create_soldier(admin_session, personal_number="9001035", hierarchy_node_id=node.id)
    commander = create_soldier(admin_session, personal_number="9001036", role="commander")
    admin_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=node.id))
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number="9001037", role="admin")
    headers = auth_headers(admin)
    send_resp = client.post("/api/notifications/announce", headers=headers, json={"title": "cascade check"})
    assert send_resp.status_code == 201
    announcement_id = send_resp.json()["id"]

    # No extra Notification row was created for the commander via the cascade path.
    commander_notif_count = len(admin_session.execute(
        select(Notification.id).where(
            Notification.reference_type == "announcement",
            Notification.reference_id == uuid.UUID(announcement_id),
            Notification.soldier_id == commander.id,
        )
    ).scalars().all())
    assert commander_notif_count == 1  # only their own entry as an ordinary recipient

    total_notif_count = len(admin_session.execute(
        select(Notification.id).where(
            Notification.reference_type == "announcement",
            Notification.reference_id == uuid.UUID(announcement_id),
        )
    ).scalars().all())

    history_resp = client.get("/api/notifications/announcements", headers=headers)
    assert history_resp.status_code == 200
    match = next(i for i in history_resp.json()["items"] if i["id"] == announcement_id)
    assert match["recipient_count"] == total_notif_count
    assert match["read_count"] <= match["recipient_count"]

    recipients_resp = client.get(f"/api/notifications/announcements/{announcement_id}/recipients", headers=headers)
    assert recipients_resp.status_code == 200
    recipient_ids = [r["soldier_id"] for r in recipients_resp.json()["items"]]
    # The commander appears at most once in the recipient list (no cascade duplicate).
    assert recipient_ids.count(str(commander.id)) == 1
    assert str(recipient.id) in recipient_ids


def test_announcement_recipients_endpoint_is_paginated(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="9001038", role="admin")
    headers = auth_headers(admin)
    for i in range(25):
        create_soldier(admin_session, personal_number=f"90010{40 + i}")
    send_resp = client.post("/api/notifications/announce", headers=headers, json={"title": "paginated recipients"})
    announcement_id = send_resp.json()["id"]

    page1 = client.get(
        f"/api/notifications/announcements/{announcement_id}/recipients",
        headers=headers, params={"offset": 0, "limit": 20},
    )
    assert page1.status_code == 200
    data1 = page1.json()
    assert len(data1["items"]) == 20
    assert data1["total"] >= 26  # 25 new soldiers + admin themself

    page2 = client.get(
        f"/api/notifications/announcements/{announcement_id}/recipients",
        headers=headers, params={"offset": 20, "limit": 20},
    )
    assert page2.status_code == 200
    data2 = page2.json()
    assert len(data2["items"]) == data2["total"] - 20
    # No overlap between the two pages.
    ids1 = {r["soldier_id"] for r in data1["items"]}
    ids2 = {r["soldier_id"] for r in data2["items"]}
    assert ids1.isdisjoint(ids2)
