"""The only supported way to write ``Soldier.email`` and ``Soldier.ad_username``.

Every write path (registration, self-service edit, admin/duty-manager edit,
enrollment review, HR sync, imports) calls these helpers so the canonical
email and the derived AD username are always stored together, collisions are
checked before the write, and a race that slips past the check is translated
from the database unique-constraint error into :class:`IdentityCollisionError`.

Error contract (all raised before any change is made to the soldier):

* ``ValueError("email_invalid" | "ad_username_too_long" | "ad_username_invalid")``
  for an unsupported address (see :mod:`app.services.identity`);
* :class:`~app.services.identity.IdentityCollisionError` (a ``ValueError``
  subclass) for a duplicate email, AD username or personal number.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import EmailVerificationToken, Soldier
from app.services.identity import IdentityCollisionError, canonical_identity

_CONSTRAINT_FIELDS = {
    "uq_soldiers_email": "email",
    "uq_soldiers_ad_username": "ad_username",
    "soldiers_personal_number_key": "personal_number",
    "ix_soldiers_personal_number": "personal_number",
}


def resolve_identity_fields(
    session: Session,
    raw_email: str | None,
    *,
    exclude_soldier_id: uuid.UUID | None = None,
) -> tuple[str | None, str | None]:
    """Canonicalize ``raw_email`` and verify nobody else owns it.

    Returns ``(email, ad_username)``; both ``None`` for a blank value. Use this
    when constructing a new ``Soldier``: ``Soldier(email=e, ad_username=u, ...)``.
    ``exclude_soldier_id`` lets a soldier keep its own values.
    """
    email, ad_username = canonical_identity(raw_email)
    if email is None:
        return None, None
    for column, value, field in (
        (Soldier.email, email, "email"),
        (Soldier.ad_username, ad_username, "ad_username"),
    ):
        query = select(Soldier.id).where(column == value)
        if exclude_soldier_id is not None:
            query = query.where(Soldier.id != exclude_soldier_id)
        if session.execute(query.limit(1)).first() is not None:
            raise IdentityCollisionError(field)
    return email, ad_username


def invalidate_verification_tokens(session: Session, soldier_id: uuid.UUID) -> None:
    """Mark every unused email verification token of the soldier as used."""
    session.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.soldier_id == soldier_id,
            EmailVerificationToken.used_at.is_(None),
        )
        .values(used_at=datetime.now(timezone.utc))
    )


def assign_soldier_email(
    session: Session,
    soldier: Soldier,
    raw_email: str | None,
    *,
    verified: bool = False,
) -> bool:
    """Set the soldier's email and AD username together. Returns True if changed.

    A blank value clears both. When the canonical email changes,
    ``email_verified`` becomes ``verified`` (default False; pass True only for
    an issuer-verified address from a consumed OIDC registration context) and
    outstanding verification tokens are invalidated. Setting the same canonical
    email again is a no-op that keeps the verification status. Raises before
    touching the soldier (see module docstring), so nothing needs rolling back.
    """
    email, ad_username = resolve_identity_fields(
        session, raw_email, exclude_soldier_id=soldier.id
    )
    if email == soldier.email and ad_username == soldier.ad_username:
        return False
    email_changed = email != soldier.email
    soldier.email = email
    soldier.ad_username = ad_username
    if email_changed:
        soldier.email_verified = verified if email is not None else False
        if soldier.id is not None:
            invalidate_verification_tokens(session, soldier.id)
    return True


def check_personal_number_available(
    session: Session,
    personal_number: str,
    *,
    exclude_soldier_id: uuid.UUID | None = None,
) -> None:
    """Raise ``IdentityCollisionError("personal_number")`` if another soldier owns it."""
    query = select(Soldier.id).where(Soldier.personal_number == personal_number)
    if exclude_soldier_id is not None:
        query = query.where(Soldier.id != exclude_soldier_id)
    if session.execute(query.limit(1)).first() is not None:
        raise IdentityCollisionError("personal_number")


def collision_from_integrity_error(exc: IntegrityError) -> IdentityCollisionError | None:
    """Map a unique-constraint violation on a soldier identity column, else None."""
    diag = getattr(exc.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    field = _CONSTRAINT_FIELDS.get(name or "")
    if field is None:
        message = str(exc.orig)
        field = next((f for n, f in _CONSTRAINT_FIELDS.items() if n in message), None)
    return IdentityCollisionError(field) if field else None


def flush_with_identity_guard(session: Session) -> None:
    """Flush; turn identity unique-constraint races into ``IdentityCollisionError``.

    The flush runs in a savepoint so the session stays usable. Other integrity
    errors propagate unchanged.
    """
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        collision = collision_from_integrity_error(exc)
        if collision is None:
            raise
        raise collision from exc


class BulkIdentityCheck:
    """Preview-time email check for a batch (imports) without a query per row.

    Built from the soldiers already loaded by the preview. ``check`` returns a
    stable error code (``email_invalid``, ``ad_username_too_long``,
    ``ad_username_invalid``, ``email_taken``, ``ad_username_taken``,
    ``email_duplicate_in_file``) or None, and remembers accepted addresses so a
    second row with the same email or AD username is flagged. It never writes.
    """

    def __init__(self, soldiers) -> None:
        self._by_email: dict[str, uuid.UUID] = {}
        self._by_ad_username: dict[str, uuid.UUID] = {}
        for soldier in soldiers:
            if soldier.email:
                self._by_email[soldier.email] = soldier.id
            if soldier.ad_username:
                self._by_ad_username[soldier.ad_username] = soldier.id
        self._seen: set[str] = set()

    def check(self, raw_email: str | None, *, own_soldier_id: uuid.UUID | None = None) -> str | None:
        try:
            email, ad_username = canonical_identity(raw_email)
        except ValueError as exc:
            return str(exc)
        if email is None:
            return None
        if self._by_email.get(email, own_soldier_id) != own_soldier_id:
            return "email_taken"
        if self._by_ad_username.get(ad_username, own_soldier_id) != own_soldier_id:
            return "ad_username_taken"
        if email in self._seen:
            return "email_duplicate_in_file"
        self._seen.add(email)
        return None
