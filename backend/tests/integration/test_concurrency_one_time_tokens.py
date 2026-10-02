"""C12 — one-time tokens redeemed twice (audit inventory T1, T2).

``action_tokens.redeem_token`` / ``redeem_token_from_link`` and
``password_reset.redeem_reset_token`` SELECT the token row ``WHERE used_at IS
NULL`` without a lock and then set ``used_at`` by primary key. Under READ
COMMITTED the second redeemer's UPDATE waits for the first commit and then
re-applies, so both calls report success.

Schedule reproduced here (two independent sessions = two clicks / two bot
callbacks / two reset form submits):
  1. both requests SELECT the unused token and meet right after that SELECT;
  2. both mark it used and commit.
Each request then dispatches the token's action (or resets the password), so
the one-time action runs twice.

Fixed (Task 4): the three redeem functions SELECT the token ``FOR UPDATE``.
The second redeemer blocks, the first's rendezvous times out and it commits,
and the second then re-checks ``used_at IS NULL`` and finds no token.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from app.db.models import PasswordResetToken, TelegramActionToken, TelegramLink
from app.services import action_tokens, password_reset
from tests.helpers import create_soldier

_CHAT_ID = 777001


def _action_token(session, soldier_id) -> str:
    token = secrets.token_hex(8)
    session.add(TelegramActionToken(
        token=token, soldier_id=soldier_id, action="constraint:approve",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    ))
    session.commit()
    return token


def _race_redeem(race, entity, redeem):
    after_select = race.rendezvous(2, "both redeemers read the unused token")

    def redeemer():
        s = race.session()
        race.pause_after_select(s, entity, after_select.wait)
        result = redeem(s)
        s.commit()
        return result

    return race.run(redeemer, redeemer)


def _assert_redeemed_once(outcomes, succeeded):
    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"redeemer crashed: {outcome.error!r}") from outcome.error
    wins = [o for o in outcomes if succeeded(o.value)]
    assert len(wins) == 1, f"token redeemed {len(wins)} times; outcomes={outcomes}"


def test_email_link_action_token_is_redeemed_once(race, admin_session):
    soldier = create_soldier(admin_session, personal_number="race-tok-link")
    token = _action_token(admin_session, soldier.id)

    outcomes = _race_redeem(
        race, TelegramActionToken,
        lambda s: action_tokens.redeem_token_from_link(s, token=token, soldier_id=soldier.id) is not None,
    )

    _assert_redeemed_once(outcomes, bool)


def test_telegram_action_token_is_redeemed_once(race, admin_session):
    soldier = create_soldier(admin_session, personal_number="race-tok-bot")
    admin_session.add(TelegramLink(soldier_id=soldier.id, telegram_chat_id=_CHAT_ID, is_verified=True))
    token = _action_token(admin_session, soldier.id)

    outcomes = _race_redeem(
        race, TelegramActionToken,
        lambda s: action_tokens.redeem_token(s, token=token, chat_id=_CHAT_ID) is not None,
    )

    _assert_redeemed_once(outcomes, bool)


def test_password_reset_token_is_redeemed_once(race, admin_session):
    soldier = create_soldier(admin_session, personal_number="race-tok-reset")
    admin_session.add(PasswordResetToken(
        soldier_id=soldier.id, token="race-reset-token", channel="email",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    ))
    admin_session.commit()

    outcomes = _race_redeem(
        race, PasswordResetToken,
        lambda s: password_reset.redeem_reset_token(s, token="race-reset-token", new_password="Race-Reset-Pass-1"),
    )

    _assert_redeemed_once(outcomes, lambda v: v == "ok")
    assert sorted(o.value for o in outcomes) == ["ok", "token_invalid"]
