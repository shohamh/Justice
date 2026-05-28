import time
import uuid

import pytest

from app.auth.jwt_tokens import (
    InvalidToken,
    decode_token,
    issue_access_token,
    issue_refresh_token,
)


def test_access_token_round_trip():
    user_id = uuid.uuid4()
    token = issue_access_token(user_id=user_id, role="soldier")
    payload = decode_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "soldier"
    assert payload["type"] == "access"


def test_refresh_token_has_different_type_claim():
    token = issue_refresh_token(user_id=uuid.uuid4())
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_invalid_token_raises():
    with pytest.raises(InvalidToken):
        decode_token("garbage.token.value")


def test_expired_token_raises(monkeypatch):
    # Issue with a 0-second lifetime
    user_id = uuid.uuid4()
    token = issue_access_token(user_id=user_id, role="soldier", lifetime_seconds=0)
    time.sleep(1)
    with pytest.raises(InvalidToken):
        decode_token(token)


def test_tampered_token_raises():
    token = issue_access_token(user_id=uuid.uuid4(), role="soldier")
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(InvalidToken):
        decode_token(tampered)
