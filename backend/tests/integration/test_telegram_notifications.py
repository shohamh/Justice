from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CommanderNotificationDepth,
    CommanderNotificationScope,
    NotificationType,
    TelegramLink,
    TelegramOutbox,
)
from app.services import notifications as svc
from app.services.settings_loader import set_setting
from tests.helpers import create_node, create_soldier


def _link_soldier(session: Session, soldier_id: uuid.UUID, chat_id: int) -> TelegramLink:
    link = TelegramLink(
        soldier_id=soldier_id,
        telegram_chat_id=chat_id,
        is_verified=True,
        notifications_enabled=True,
    )
    session.add(link)
    session.flush()
    return link


def _enable_telegram(session: Session) -> None:
    """telegram.enabled now defaults to off, so any test exercising push
    delivery must opt in explicitly."""
    set_setting(session, key="telegram.enabled", value=True, actor_id=None)
    session.flush()


def test_enqueue_push_creates_outbox_with_keyboard(admin_session: Session):
    """Push notification for actionable type creates outbox row with reply_markup_json."""
    _enable_telegram(admin_session)
    s = create_soldier(admin_session, personal_number="TN001")
    _link_soldier(admin_session, s.id, 1001)
    resource_id = uuid.uuid4()

    svc.create_notification(
        admin_session,
        soldier_id=s.id,
        type=NotificationType.constraint_pending,
        title="אילוץ ממתין לאישור",
        reference_type="personal_constraint",
        reference_id=resource_id,
    )
    admin_session.flush()

    row = admin_session.execute(
        select(TelegramOutbox).where(TelegramOutbox.telegram_chat_id == 1001)
    ).scalar_one_or_none()
    assert row is not None
    assert row.reply_markup_json is not None

    keyboard = json.loads(row.reply_markup_json)["inline_keyboard"]
    # First row: approve + reject buttons
    assert len(keyboard[0]) == 2
    assert "אשר" in keyboard[0][0]["text"]
    assert "דחה" in keyboard[0][1]["text"]
    # callback_data is a 16-char token
    assert len(keyboard[0][0]["callback_data"]) == 16


def test_enqueue_push_informational_type_has_no_approve_row(admin_session: Session):
    """Informational notification has no approve/reject row, just silence + link."""
    _enable_telegram(admin_session)
    s = create_soldier(admin_session, personal_number="TN002")
    _link_soldier(admin_session, s.id, 1002)

    svc.create_notification(
        admin_session,
        soldier_id=s.id,
        type=NotificationType.announcement,
        title="הכרזה",
    )
    admin_session.flush()

    row = admin_session.execute(
        select(TelegramOutbox).where(TelegramOutbox.telegram_chat_id == 1002)
    ).scalar_one()
    keyboard = json.loads(row.reply_markup_json)["inline_keyboard"]
    flat = [btn for row in keyboard for btn in row]
    texts = [b["text"] for b in flat]
    assert not any("אשר" in t for t in texts)
    assert any("השתק" in t for t in texts)


def test_gender_aware_open_label_female(admin_session: Session):
    """Female soldier gets 'פתחי במערכת' label."""
    _enable_telegram(admin_session)
    s = create_soldier(admin_session, personal_number="TN003")
    s.gender = "female"
    admin_session.flush()
    _link_soldier(admin_session, s.id, 1003)

    svc.create_notification(
        admin_session, soldier_id=s.id, type=NotificationType.announcement, title="test"
    )
    admin_session.flush()

    row = admin_session.execute(
        select(TelegramOutbox).where(TelegramOutbox.telegram_chat_id == 1003)
    ).scalar_one()
    assert "פתחי" in row.reply_markup_json


def test_cascade_depth_filtering_excludes_deep_soldiers(admin_session: Session):
    """Commander with max_depth=1 does not receive cascade for a grandchild soldier."""
    root = create_node(admin_session, level="division", name="DIV-TN")
    mid = create_node(admin_session, level="unit", name="UNIT-TN", parent=root)
    leaf = create_node(admin_session, level="department", name="DEPT-TN", parent=mid)

    commander = create_soldier(admin_session, personal_number="TN-CMD1", role="commander")
    _link_soldier(admin_session, commander.id, 2001)
    admin_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=root.id))
    admin_session.add(CommanderNotificationDepth(
        commander_id=commander.id,
        notification_type=NotificationType.constraint_pending,
        max_depth=1,
    ))
    # Soldier is at leaf (2 levels below root)
    soldier = create_soldier(admin_session, personal_number="TN-S1", hierarchy_node_id=leaf.id)
    admin_session.flush()

    svc.notify_commanders_of_request(
        admin_session,
        soldier_id=soldier.id,
        type=NotificationType.constraint_pending,
        title="אילוץ",
        reference_type="personal_constraint",
        reference_id=uuid.uuid4(),
    )
    admin_session.flush()

    outbox = list(admin_session.execute(
        select(TelegramOutbox).where(TelegramOutbox.telegram_chat_id == 2001)
    ).scalars().all())
    assert outbox == []


def test_cascade_depth_filtering_includes_within_depth(admin_session: Session):
    """Commander with max_depth=2 (default) receives cascade for grandchild soldier."""
    _enable_telegram(admin_session)
    root = create_node(admin_session, level="division", name="DIV-TN2")
    mid = create_node(admin_session, level="unit", name="UNIT-TN2", parent=root)
    leaf = create_node(admin_session, level="department", name="DEPT-TN2", parent=mid)

    commander = create_soldier(admin_session, personal_number="TN-CMD2", role="commander")
    _link_soldier(admin_session, commander.id, 2002)
    admin_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=root.id))
    # No depth row — default is 2
    soldier = create_soldier(admin_session, personal_number="TN-S2", hierarchy_node_id=leaf.id)
    admin_session.flush()

    svc.notify_commanders_of_request(
        admin_session,
        soldier_id=soldier.id,
        type=NotificationType.constraint_pending,
        title="אילוץ",
        reference_type="personal_constraint",
        reference_id=uuid.uuid4(),
    )
    admin_session.flush()

    outbox = list(admin_session.execute(
        select(TelegramOutbox).where(TelegramOutbox.telegram_chat_id == 2002)
    ).scalars().all())
    assert len(outbox) == 1


def test_enqueue_push_skipped_when_telegram_disabled(admin_session: Session):
    """No outbox row is created when the telegram.enabled system setting is off."""
    from app.services.settings_loader import set_setting

    set_setting(admin_session, key="telegram.enabled", value=False, actor_id=None)
    admin_session.flush()

    s = create_soldier(admin_session, personal_number="TN004")
    _link_soldier(admin_session, s.id, 1004)

    svc.create_notification(
        admin_session,
        soldier_id=s.id,
        type=NotificationType.announcement,
        title="הכרזה",
    )
    admin_session.flush()

    row = admin_session.execute(
        select(TelegramOutbox).where(TelegramOutbox.telegram_chat_id == 1004)
    ).scalar_one_or_none()
    assert row is None


def test_constraint_submit_notifies_commanders(admin_session: Session):
    """Submitting a constraint creates a constraint_pending outbox row for commander."""
    from app.db.models import CommanderNotificationScope, TelegramLink
    from app.services.constraints import submit_constraint
    from datetime import date, timedelta
    from sqlalchemy import select

    _enable_telegram(admin_session)
    root = create_node(admin_session, level="division", name="DIV-CS")
    soldier = create_soldier(admin_session, personal_number="CS-S1", hierarchy_node_id=root.id)
    commander = create_soldier(admin_session, personal_number="CS-CMD1", role="commander")
    admin_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=root.id))
    link = TelegramLink(
        soldier_id=commander.id, telegram_chat_id=3001,
        is_verified=True, notifications_enabled=True,
    )
    admin_session.add(link)
    admin_session.flush()

    today = date.today()
    submit_constraint(
        admin_session, soldier_id=soldier.id,
        start_date=today + timedelta(days=5),
        end_date=today + timedelta(days=6),
        reason="test",
    )
    admin_session.flush()

    import json
    outbox = list(admin_session.execute(
        select(TelegramOutbox).where(TelegramOutbox.telegram_chat_id == 3001)
    ).scalars().all())
    assert len(outbox) == 1
    keyboard = json.loads(outbox[0].reply_markup_json)["inline_keyboard"]
    assert any("אשר" in btn["text"] for row in keyboard for btn in row)
