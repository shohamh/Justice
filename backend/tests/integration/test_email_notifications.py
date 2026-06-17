import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import EmailOutbox, NotificationPreference, NotificationType, Soldier
from app.services.notifications import create_notification
from tests.helpers import auth_headers, create_soldier


def _soldier_with_email(session: Session, personal_number: str, verified: bool = True) -> Soldier:
    s = create_soldier(session, personal_number=personal_number)
    s.email = f"{personal_number}@test.com"
    s.email_verified = verified
    session.flush()
    return s


# --- enqueue behavior ---

def test_email_enqueued_for_verified_soldier(admin_session: Session):
    s = _soldier_with_email(admin_session, "8001001")
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="הודעה")
    admin_session.flush()
    rows = admin_session.query(EmailOutbox).filter_by(to_address=s.email).all()
    assert len(rows) == 1
    assert "הודעה" in rows[0].html_body
    assert rows[0].sent_at is None


def test_email_not_enqueued_for_unverified_soldier(admin_session: Session):
    s = _soldier_with_email(admin_session, "8001002", verified=False)
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="הודעה")
    admin_session.flush()
    rows = admin_session.query(EmailOutbox).filter_by(to_address=s.email).all()
    assert len(rows) == 0


def test_email_not_enqueued_when_no_email(admin_session: Session):
    s = create_soldier(admin_session, personal_number="8001003")
    assert s.email is None
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="הודעה")
    admin_session.flush()
    rows = admin_session.query(EmailOutbox).all()
    assert all(r.to_address != f"8001003@test.com" for r in rows)


def test_email_not_enqueued_when_email_enabled_false(admin_session: Session):
    s = _soldier_with_email(admin_session, "8001004")
    pref = NotificationPreference(
        soldier_id=s.id,
        notification_type=NotificationType.announcement,
        in_app_enabled=True,
        push_enabled=False,
        email_enabled=False,
    )
    admin_session.add(pref)
    admin_session.flush()
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="הודעה")
    admin_session.flush()
    rows = admin_session.query(EmailOutbox).filter_by(to_address=s.email).all()
    assert len(rows) == 0


def test_email_subject_matches_title(admin_session: Session):
    s = _soldier_with_email(admin_session, "8001005")
    create_notification(admin_session, soldier_id=s.id, type=NotificationType.announcement,
                        title="נושא חשוב")
    admin_session.flush()
    row = admin_session.query(EmailOutbox).filter_by(to_address=s.email).one()
    assert row.subject == "נושא חשוב"


# --- preference defaults ---

def test_email_enabled_default_true(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8001006")
    headers = auth_headers(s)
    resp = client.get("/api/notifications/preferences", headers=headers)
    assert resp.status_code == 200
    for p in resp.json():
        assert p["email_enabled"] is True


def test_update_email_enabled_preference(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="8001007")
    headers = auth_headers(s)
    resp = client.put("/api/notifications/preferences", headers=headers, json={
        "preferences": [{"notification_type": "announcement", "email_enabled": False}]
    })
    assert resp.status_code == 200
    updated = {p["notification_type"]: p for p in resp.json()}
    assert updated["announcement"]["email_enabled"] is False
    # other types unaffected
    assert updated["swap_accepted"]["email_enabled"] is True


# --- POST /api/action token redemption ---

def test_redeem_action_token_from_link_invalid(client: TestClient, admin_session: Session):
    """Test that an invalid action token returns 404."""
    s = create_soldier(admin_session, personal_number="8001008")
    headers = auth_headers(s)
    resp = client.post("/api/action", headers=headers, json={"token": "invalid_token"})
    assert resp.status_code == 404


def test_redeem_action_token_wrong_soldier(client: TestClient, admin_session: Session):
    """Test that a token belonging to another soldier cannot be redeemed."""
    from app.services.action_tokens import create_token
    owner = create_soldier(admin_session, personal_number="8001009")
    attacker = create_soldier(admin_session, personal_number="8001010")
    tok = create_token(admin_session, soldier_id=owner.id, action="constraint:approve", resource_id=None)
    admin_session.commit()
    headers = auth_headers(attacker)
    resp = client.post("/api/action", headers=headers, json={"token": tok})
    assert resp.status_code == 404
