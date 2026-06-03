from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.db.models import TelegramActionToken, TelegramLink


def _soldier_id():
    return uuid.uuid4()


def test_create_token_returns_16_char_hex():
    from app.services.action_tokens import create_token

    session = MagicMock()
    sid = _soldier_id()
    session.flush.return_value = None

    token = create_token(session, soldier_id=sid, action="constraint:approve")

    assert len(token) == 16
    assert all(c in "0123456789abcdef" for c in token)
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, TelegramActionToken)
    assert added.action == "constraint:approve"
    assert added.soldier_id == sid


def test_create_token_with_resource():
    from app.services.action_tokens import create_token

    session = MagicMock()
    sid = _soldier_id()
    rid = uuid.uuid4()

    token = create_token(
        session,
        soldier_id=sid,
        action="exemption:reject",
        resource_type="exemption_request",
        resource_id=rid,
    )

    added = session.add.call_args[0][0]
    assert added.resource_type == "exemption_request"
    assert added.resource_id == rid


def test_redeem_token_returns_none_for_missing():
    from app.services.action_tokens import redeem_token

    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    result = redeem_token(session, token="0000000000000000", chat_id=123)
    assert result is None


def test_redeem_token_returns_none_when_link_mismatch():
    from app.services.action_tokens import redeem_token

    session = MagicMock()
    sid = _soldier_id()
    token_row = TelegramActionToken(
        token="abcd1234abcd1234",
        soldier_id=sid,
        action="constraint:approve",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    # First execute returns the token, second returns None (no matching link)
    session.execute.return_value.scalar_one_or_none.side_effect = [token_row, None]

    result = redeem_token(session, token="abcd1234abcd1234", chat_id=999)
    assert result is None


def test_find_pending_reply_returns_none_when_no_match():
    from app.services.action_tokens import find_pending_reply

    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    result = find_pending_reply(session, chat_id=42)
    assert result is None


def test_set_awaiting_reply_returns_false_for_missing_token():
    from app.services.action_tokens import set_awaiting_reply

    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    result = set_awaiting_reply(session, token="notexist00000000", chat_id=42)
    assert result is False


def test_set_awaiting_reply_sets_chat_id():
    from app.services.action_tokens import set_awaiting_reply

    session = MagicMock()
    sid = _soldier_id()
    token_row = TelegramActionToken(
        token="abcd1234abcd1234",
        soldier_id=sid,
        action="constraint:reject",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    session.execute.return_value.scalar_one_or_none.return_value = token_row

    result = set_awaiting_reply(session, token="abcd1234abcd1234", chat_id=77)

    assert result is True
    assert token_row.awaiting_text_from_chat_id == 77
