from __future__ import annotations

import pytest

from app.services.notifications import AnnouncementRateLimitError, broadcast_announcement
from tests.helpers import create_soldier


def test_broadcast_blocks_duplicate_title_within_cooldown(admin_session):
    sender = create_soldier(admin_session, personal_number="8000001", role="admin")
    broadcast_announcement(admin_session, title="בדיקה", body="תוכן", actor_id=sender.id)
    admin_session.commit()
    with pytest.raises(AnnouncementRateLimitError, match="duplicate_announcement_cooldown"):
        broadcast_announcement(admin_session, title="בדיקה", body="תוכן שונה", actor_id=sender.id)


def test_broadcast_allows_different_title_immediately(admin_session):
    sender = create_soldier(admin_session, personal_number="8000002", role="admin")
    broadcast_announcement(admin_session, title="הודעה א", actor_id=sender.id)
    admin_session.commit()
    # A genuinely different announcement from the same sender must not be blocked
    a2 = broadcast_announcement(admin_session, title="הודעה ב", actor_id=sender.id)
    admin_session.commit()
    assert a2.title == "הודעה ב"


def test_broadcast_allows_same_title_from_different_sender(admin_session):
    sender1 = create_soldier(admin_session, personal_number="8000003", role="admin")
    sender2 = create_soldier(admin_session, personal_number="8000004", role="admin")
    broadcast_announcement(admin_session, title="הודעה משותפת", actor_id=sender1.id)
    admin_session.commit()
    a2 = broadcast_announcement(admin_session, title="הודעה משותפת", actor_id=sender2.id)
    admin_session.commit()
    assert a2.sender_id == sender2.id
