import uuid
from fastapi.testclient import TestClient

from app.audit.writer import write_audit
from tests.helpers import create_soldier


def test_admin_audit_log_requires_admin(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="audit-plain")
    admin_session.flush()
    from tests.helpers import auth_headers
    r = client.get("/api/admin/audit-logs", headers=auth_headers(soldier))
    assert r.status_code == 403


def test_admin_audit_log_returns_entries_and_filters(client, admin_session):
    from sqlalchemy import text

    from tests.helpers import auth_headers

    admin = create_soldier(admin_session, personal_number="audit-admin-2", role="admin")
    actor = create_soldier(admin_session, personal_number="audit-actor")
    admin_session.flush()

    exemption_id = uuid.uuid4()
    write_audit(
        admin_session,
        actor_id=actor.id,
        action="exemption.grant",
        entity_type="soldier_exemption",
        entity_id=exemption_id,
        before={"status": "pending_commander"},
        after={"status": "approved", "exemption_type": "פטור מבחן"},
        context={"reason": "בקשה אושרה"},
    )
    write_audit(
        admin_session,
        actor_id=admin.id,
        action="duty_config.update",
        entity_type="duty_type",
        entity_id=uuid.uuid4(),
    )
    admin_session.commit()

    r = client.get("/api/admin/audit-logs", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    actions = {item["action"] for item in body["items"]}
    assert {"exemption.grant", "duty_config.update"} <= actions
    assert body["facets"]["actions"]
    assert body["facets"]["entity_types"]
    assert any(a["full_name"] for a in body["facets"]["actors"])
    # actor names resolved on items
    by_action = {item["action"]: item for item in body["items"]}
    assert by_action["exemption.grant"]["actor_name"] == actor.full_name
    # JSONB payloads are included for the detail view
    grant = by_action["exemption.grant"]
    assert grant["before"] == {"status": "pending_commander"}
    assert grant["after"]["status"] == "approved"
    assert grant["context"] == {"reason": "בקשה אושרה"}
    assert by_action["duty_config.update"]["before"] is None
    # entity existence: exemption entity id is random -> reported deleted;
    # duty_config entity id is also random -> deleted; both have links
    assert by_action["exemption.grant"]["entity_exists"] is False
    assert by_action["exemption.grant"]["entity_link"] is None
    assert by_action["duty_config.update"]["entity_exists"] is False
    assert by_action["duty_config.update"]["entity_link"] == "/planning/config"

    # action substring filter
    r2 = client.get(
        "/api/admin/audit-logs",
        params={"action": "exemption"},
        headers=auth_headers(admin),
    )
    body2 = r2.json()
    assert body2["total"] >= 1
    assert all("exemption" in item["action"] for item in body2["items"])

    # actor filter
    r3 = client.get(
        "/api/admin/audit-logs",
        params={"actor_id": str(actor.id)},
        headers=auth_headers(admin),
    )
    assert all(item["actor_id"] == str(actor.id) for item in r3.json()["items"])
    assert r3.json()["items"]


def test_admin_audit_log_pagination(client, admin_session):
    from tests.helpers import auth_headers

    admin = create_soldier(admin_session, personal_number="audit-admin-3", role="admin")
    admin_session.flush()
    for i in range(5):
        write_audit(
            admin_session,
            actor_id=admin.id,
            action=f"bulk.action.{i}",
            entity_type="test",
        )
    admin_session.commit()

    r = client.get(
        "/api/admin/audit-logs",
        params={"action": "bulk.action", "limit": 2, "offset": 0},
        headers=auth_headers(admin),
    )
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2

    r2 = client.get(
        "/api/admin/audit-logs",
        params={"action": "bulk.action", "limit": 2, "offset": 2},
        headers=auth_headers(admin),
    )
    body2 = r2.json()
    assert len(body2["items"]) == 2
    assert body2["items"][0]["id"] != body["items"][0]["id"]


def test_admin_audit_log_links_existing_entities(client, admin_session):
    from tests.helpers import auth_headers

    admin = create_soldier(admin_session, personal_number="audit-admin-4", role="admin")
    soldier = create_soldier(admin_session, personal_number="audit-soldier-4")
    admin_session.flush()

    write_audit(
        admin_session,
        actor_id=admin.id,
        action="soldier.update",
        entity_type="soldier",
        entity_id=soldier.id,
    )
    write_audit(
        admin_session,
        actor_id=admin.id,
        action="duty_type.create",
        entity_type="duty_type",
        entity_id=uuid.uuid4(),
    )
    admin_session.commit()

    r = client.get(
        "/api/admin/audit-logs",
        params={"action": "soldier.update"},
        headers=auth_headers(admin),
    )
    item = r.json()["items"][0]
    assert item["entity_exists"] is True
    assert item["entity_link"] == "/team"

    r2 = client.get(
        "/api/admin/audit-logs",
        params={"action": "duty_type.create"},
        headers=auth_headers(admin),
    )
    item2 = r2.json()["items"][0]
    assert item2["entity_exists"] is False
    assert item2["entity_link"] == "/planning/config"
