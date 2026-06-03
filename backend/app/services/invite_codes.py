from __future__ import annotations

import secrets
import string
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RegistrationInviteCode


class InviteCodeError(Exception):
    pass


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def create_invite_code(
    session: Session, *, uses_left: int, actor_id: uuid.UUID | None
) -> RegistrationInviteCode:
    code = RegistrationInviteCode(code=_generate_code(), uses_left=uses_left, created_by=actor_id)
    session.add(code)
    session.flush()
    return code


def validate_code(session: Session, *, code: str) -> bool:
    row = session.execute(
        select(RegistrationInviteCode).where(RegistrationInviteCode.code == code)
    ).scalar_one_or_none()
    return row is not None and row.uses_left > 0


def consume_invite_code(session: Session, *, code: str) -> RegistrationInviteCode:
    row = session.execute(
        select(RegistrationInviteCode).where(RegistrationInviteCode.code == code)
    ).scalar_one_or_none()
    if row is None:
        raise InviteCodeError("invalid invite code")
    if row.uses_left <= 0:
        raise InviteCodeError("invite code exhausted")
    row.uses_left -= 1
    session.flush()
    return row
