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

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import EmailVerificationToken, Soldier
from app.services import email_verification
from tests.helpers import create_soldier, set_soldier_email

_EMAIL = "race-shared@example.test"


def test_two_accounts_cannot_hold_one_email(admin_session):
    """C15 is now closed at the schema: ``uq_soldiers_email`` (soldier identity
    migration) makes it impossible for two accounts to hold, let alone both
    verify, one address, so the two-verifications race can no longer be set up.
    ``verify_token`` keeps its per-email advisory lock for legacy data."""
    first = create_soldier(admin_session, personal_number="race-ev-1")
    set_soldier_email(first, _EMAIL)
    admin_session.commit()
    second = create_soldier(admin_session, personal_number="race-ev-2")
    set_soldier_email(second, _EMAIL)
    with pytest.raises(IntegrityError):
        admin_session.flush()
    admin_session.rollback()


def test_verification_and_email_change_of_one_soldier_do_not_deadlock(race, admin_session, monkeypatch):
    """M1 — ``verify_token`` locked the token row, then (at flush) UPDATEd the
    soldier. ``PATCH /me/email`` UPDATEs the soldier (autoflush) and then
    ``request_verification`` UPDATEs the soldier's unused tokens: the reverse
    order on the same two rows when one user verifies and changes their
    address at the same time.

    Fixed: ``verify_token`` locks the soldier before the token (soldier ->
    token -> email lock), the order the email change already uses."""
    from app.routes import me as me_routes

    monkeypatch.setattr(email_verification, "send_email", lambda **_kw: True)
    soldier = create_soldier(admin_session, personal_number="race-ev-m1")
    set_soldier_email(soldier, "race-m1-old@example.test")
    admin_session.add(EmailVerificationToken(
        soldier_id=soldier.id, email=soldier.email, token="race-m1-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    ))
    admin_session.commit()
    soldier_id = soldier.id

    verify_read_token = race.signal("verification read the token")
    change_holds_soldier = race.signal("email change holds the soldier row")

    def verify():
        s = race.session()

        def _after_token_read():
            verify_read_token.set()
            change_holds_soldier.wait()

        race.pause_after_select(s, EmailVerificationToken, _after_token_read)
        result = email_verification.verify_token(s, token="race-m1-token")
        s.commit()
        return result

    def change_email():
        verify_read_token.wait()
        s = race.session()
        user = s.get(Soldier, soldier_id)
        # request_verification's token SELECT autoflushes the soldier UPDATE first.
        race.pause_after_select(s, EmailVerificationToken, change_holds_soldier.set)
        return me_routes.set_email(
            body=me_routes.SetEmailRequest(email="race-m1-new@example.test"), session=s, user=user,
        )

    outcomes = race.run(verify, change_email)

    assert all(o.ok for o in outcomes), f"outcomes={outcomes}"
    admin_session.expire_all()
    final = admin_session.get(Soldier, soldier_id)
    assert final.email == "race-m1-new@example.test"
    assert final.email_verified is False
