import pytest
from sqlalchemy import select

from app.db.models import RegistrationInviteCode
from app.services.invite_codes import InviteCodeError, consume_invite_code, validate_code


def test_consume_decrements_uses_left(admin_session):
    admin_session.add(RegistrationInviteCode(code="ABC123", uses_left=2))
    admin_session.flush()
    row = consume_invite_code(admin_session, code="ABC123")
    admin_session.commit()
    assert row.uses_left == 1


def test_consume_raises_when_exhausted(admin_session):
    admin_session.add(RegistrationInviteCode(code="EXH001", uses_left=0))
    admin_session.flush()
    with pytest.raises(InviteCodeError, match="exhausted"):
        consume_invite_code(admin_session, code="EXH001")


def test_consume_raises_when_not_found(admin_session):
    with pytest.raises(InviteCodeError, match="invalid"):
        consume_invite_code(admin_session, code="NOPE")


def test_concurrent_consume_never_over_redeems(admin_session, admin_engine):
    """Two concurrent redemptions of a single-use code must not both succeed."""
    admin_session.add(RegistrationInviteCode(code="RACE01", uses_left=1))
    admin_session.commit()

    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    s1 = SessionLocal()
    s2 = SessionLocal()
    try:
        row1 = consume_invite_code(s1, code="RACE01")
        s1.commit()
        with pytest.raises(InviteCodeError, match="exhausted"):
            consume_invite_code(s2, code="RACE01")
        s2.rollback()
    finally:
        s1.close()
        s2.close()

    row = admin_session.execute(
        select(RegistrationInviteCode).where(RegistrationInviteCode.code == "RACE01")
    ).scalar_one()
    assert row.uses_left == 0
