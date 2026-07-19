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


def test_execute_action_swap_approve_requester_delegates_to_approve_manager_side():
    from bot.actions import execute_action
    from app.db.models import SwapRequest

    session = MagicMock()
    token = _make_token("swap:approve_requester")
    session.get.return_value = MagicMock(spec=SwapRequest)

    with patch("bot.actions.swap_svc.approve_manager_side") as mock_approve:
        mock_approve.return_value = MagicMock()
        result = execute_action(token, session)

    assert mock_approve.call_count == 1
    _, kwargs = mock_approve.call_args
    assert kwargs["request_id"] == token.resource_id
    assert kwargs["side"] == "requester"
    assert kwargs["actor_id"] == token.soldier_id
    assert callable(kwargs["is_authorized_override"])
    assert "אושרה" in result


def test_execute_action_swap_approve_requester_override_callable_reflects_can():
    """The is_authorized_override callable passed to approve_manager_side must
    resolve to True when the actor is authorized (e.g. an admin/duty-manager
    outside the chain) and False otherwise — exercised directly here since the
    real chain-membership branching now lives entirely in
    app.services.swaps.approve_manager_side."""
    from bot.actions import execute_action
    from app.db.models import HierarchyNode, Soldier, SwapRequest

    session = MagicMock()
    token = _make_token("swap:approve_requester")

    req = MagicMock(spec=SwapRequest)
    req.requesting_soldier_id = uuid.uuid4()
    requester = MagicMock(spec=Soldier)
    requester.hierarchy_node_id = uuid.uuid4()
    node = MagicMock(spec=HierarchyNode)
    node.path_ids = [uuid.uuid4()]
    actor = MagicMock(spec=Soldier)
    actor.id = token.soldier_id
    actor.role = "admin"

    def _get(model, obj_id):
        if model is SwapRequest:
            return req
        if model is Soldier and obj_id == token.soldier_id:
            return actor
        if model is Soldier:
            return requester
        if model is HierarchyNode:
            return node
        return None

    session.get.side_effect = _get

    with patch("bot.actions.swap_svc.approve_manager_side") as mock_approve:
        mock_approve.return_value = MagicMock()
        execute_action(token, session)

    _, kwargs = mock_approve.call_args
    assert kwargs["is_authorized_override"]() is True  # admin is authorized


def test_execute_action_swap_approve_requester_unauthorized_stranger_override_is_false():
    from bot.actions import execute_action
    from app.db.models import HierarchyNode, Soldier, SwapRequest
    from app.services import swaps as swap_svc

    session = MagicMock()
    token = _make_token("swap:approve_requester")

    req = MagicMock(spec=SwapRequest)
    req.requesting_soldier_id = uuid.uuid4()
    requester = MagicMock(spec=Soldier)
    requester.hierarchy_node_id = uuid.uuid4()
    node = MagicMock(spec=HierarchyNode)
    node.path_ids = [uuid.uuid4()]
    actor = MagicMock(spec=Soldier)
    actor.id = token.soldier_id
    actor.role = "soldier"
    actor.rank = None

    def _get(model, obj_id):
        if model is SwapRequest:
            return req
        if model is Soldier and obj_id == token.soldier_id:
            return actor
        if model is Soldier:
            return requester
        if model is HierarchyNode:
            return node
        return None

    session.get.side_effect = _get
    session.execute.return_value.scalars.return_value.all.return_value = []
    session.execute.return_value.first.return_value = None

    with patch(
        "bot.actions.swap_svc.approve_manager_side",
        side_effect=lambda *a, is_authorized_override, **k: (_ for _ in ()).throw(
            swap_svc.SwapError("forbidden")
        ) if not is_authorized_override() else None,
    ):
        result = execute_action(token, session)

    assert "forbidden" in result or "שגיאה" in result


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
