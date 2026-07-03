from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.db.models import (
    CommanderNotificationDepth,
    NotificationPreference,
    NotificationType,
    TelegramActionToken,
)


def _make_token(action: str, resource_id: uuid.UUID | None = None, extra_json: dict | None = None) -> TelegramActionToken:
    return TelegramActionToken(
        token="abcd1234abcd1234",
        soldier_id=uuid.uuid4(),
        action=action,
        resource_type="personal_constraint",
        resource_id=resource_id or uuid.uuid4(),
        extra_json=extra_json,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


def test_execute_action_constraint_approve_calls_service():
    from bot.actions import execute_action

    session = MagicMock()
    token = _make_token("constraint:approve")

    with patch("bot.actions.constraint_svc.approve_constraint") as mock_approve:
        mock_approve.return_value = MagicMock()
        result = execute_action(token, session)

    mock_approve.assert_called_once_with(
        session, constraint_id=token.resource_id, actor_id=token.soldier_id
    )
    assert "אושרה" in result


def test_execute_action_exemption_approve_commander_step_calls_service():
    from bot.actions import execute_action

    session = MagicMock()
    token = _make_token("exemption:approve")
    req = MagicMock()
    req.status = "pending_commander"
    session.get.return_value = req

    with patch("bot.actions.exemption_svc.approve_commander_step") as mock_approve:
        mock_approve.return_value = MagicMock()
        result = execute_action(token, session)

    mock_approve.assert_called_once_with(
        session, token.resource_id, approved_by=token.soldier_id
    )
    assert "אושרה" in result


def test_execute_action_exemption_approve_duty_manager_step_calls_service():
    from bot.actions import execute_action

    session = MagicMock()
    token = _make_token("exemption:approve")
    req = MagicMock()
    req.status = "pending_duty_manager"
    session.get.return_value = req

    with patch("bot.actions.exemption_svc.approve_duty_manager_step") as mock_approve:
        mock_approve.return_value = MagicMock()
        result = execute_action(token, session)

    mock_approve.assert_called_once_with(
        session, token.resource_id, decided_by=token.soldier_id
    )
    assert "אושרה" in result


def test_execute_action_with_reason_constraint_reject():
    from bot.actions import execute_action_with_reason

    session = MagicMock()
    token = _make_token("constraint:reject")

    with patch("bot.actions.constraint_svc.reject_constraint") as mock_reject:
        mock_reject.return_value = MagicMock()
        result = execute_action_with_reason(token, session, reason="סיבה לדחייה")

    mock_reject.assert_called_once_with(
        session, constraint_id=token.resource_id, actor_id=token.soldier_id, decision_note="סיבה לדחייה"
    )
    assert "נדחתה" in result


def test_execute_action_with_reason_swap_reject():
    from bot.actions import execute_action_with_reason

    session = MagicMock()
    token = _make_token("swap:reject")

    with patch("bot.actions.swap_svc.reject_request") as mock_reject:
        mock_reject.return_value = MagicMock()
        result = execute_action_with_reason(token, session, reason="לא מתאים")

    mock_reject.assert_called_once_with(
        session, request_id=token.resource_id, decision_note="לא מתאים", actor_id=token.soldier_id
    )
    assert "נדחתה" in result


def test_execute_silence_step1_regular_soldier_sets_push_disabled():
    from bot.actions import execute_silence_step1

    session = MagicMock()
    from app.db.models import Soldier
    soldier = MagicMock(spec=Soldier)
    soldier.role = "soldier"
    session.get.return_value = soldier
    session.execute.return_value.scalar_one_or_none.return_value = None

    token = _make_token("silence:step1", extra_json={"notification_type": "announcement"})

    result = execute_silence_step1(token, session, chat_id=123)

    assert isinstance(result, str)
    assert "הושתקו" in result
    session.add.assert_called()  # NotificationPreference row added


def test_execute_silence_step1_commander_returns_keyboard_tuple():
    from bot.actions import execute_silence_step1

    session = MagicMock()
    from app.db.models import Soldier
    soldier = MagicMock(spec=Soldier)
    soldier.role = "commander"
    soldier.id = uuid.uuid4()
    session.get.return_value = soldier
    # No existing pref or depth row
    session.execute.return_value.scalar_one_or_none.return_value = None

    token = _make_token("silence:step1", extra_json={"notification_type": "constraint_pending"})
    token.soldier_id = soldier.id

    result = execute_silence_step1(token, session, chat_id=123)

    assert isinstance(result, tuple)
    text, markup = result
    assert "רמות" in text


def test_execute_silence_depth_upserts_row():
    from bot.actions import execute_silence_depth

    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    token = _make_token("silence:depth", extra_json={
        "notification_type": "constraint_pending",
        "depth": 1,
    })

    result = execute_silence_depth(token, session, chat_id=123)

    session.add.assert_called()
    added = session.add.call_args[0][0]
    assert isinstance(added, CommanderNotificationDepth)
    assert added.max_depth == 1
    assert "עודכן" in result
