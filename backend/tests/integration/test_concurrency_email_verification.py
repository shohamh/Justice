"""C15 — two accounts verify the same email address (audit inventory T4).

``email_verification.verify_token`` checks that no *other* soldier has already
verified the token's email, then sets ``email_verified``. Nothing in the schema
enforces one verified account per email, and the check is not serialized.

Schedule reproduced here (two independent sessions = two verification links
clicked by two soldiers who entered the same address):
  1. both requests run the "already verified by someone else?" query and see
     no conflict, and meet right after it;
  2. both set ``email_verified`` and commit.
Two accounts end up verified for one email; password reset by email and other
email lookups then match two accounts.

Fixed (Task 4): ``verify_token`` locks the token row and then takes a per-email
advisory lock before the conflict check. The second verification blocks on it,
the first's rendezvous times out and it commits, and the second then sees the
verified account and returns ``email_taken``. No unique index was added: a
partial unique index could fail to build on existing duplicate data, and
``verify_token`` is the only writer of ``email_verified = true``.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import event, func, inspect, select

from app.db.models import EmailVerificationToken, Soldier
from app.services import email_verification
from tests.helpers import create_soldier

_EMAIL = "race-shared@example.test"


def _pause_after_nth_select(session, entity, n, hook):
    """Like RaceKit.pause_after_select, but on the n-th SELECT of ``entity``."""
    mapper = inspect(entity)
    seen = 0

    def _after(state):
        nonlocal seen
        if not state.is_select or mapper not in state.all_mappers:
            return None
        seen += 1
        if seen != n:
            return None
        result = state.invoke_statement().freeze()
        hook()
        return result()

    event.listen(session, "do_orm_execute", _after)


def test_two_accounts_cannot_both_verify_one_email(race, admin_session):
    tokens = []
    for n in (1, 2):
        soldier = create_soldier(admin_session, personal_number=f"race-ev-{n}")
        soldier.email = _EMAIL
        token = f"race-email-token-{n}"
        admin_session.add(EmailVerificationToken(
            soldier_id=soldier.id, email=_EMAIL, token=token,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ))
        tokens.append(token)
    admin_session.commit()

    after_conflict_check = race.rendezvous(2, "both verifications found no conflicting account")

    def verify(token):
        def _call():
            s = race.session()
            # 1st Soldier SELECT loads the token's soldier, 2nd is the conflict check.
            _pause_after_nth_select(s, Soldier, 2, after_conflict_check.wait)
            result = email_verification.verify_token(s, token=token)
            s.commit()
            return result
        return _call

    outcomes = race.run(verify(tokens[0]), verify(tokens[1]))

    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"verification crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    verified = admin_session.execute(
        select(func.count()).select_from(Soldier).where(Soldier.email == _EMAIL, Soldier.email_verified.is_(True))
    ).scalar_one()
    assert verified == 1, f"{verified} accounts verified {_EMAIL}; outcomes={outcomes}"
    assert sorted(o.value for o in outcomes) == ["email_taken", "ok"]
