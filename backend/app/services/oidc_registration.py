"""Registration contexts for verified OIDC identities that match no soldier.

The context replaces the invite code. It is only ever honoured when the
request carries the browser cookie whose hash is stored here, it is read under
a row lock (so concurrent final steps serialize) and consumed in the caller's
transaction together with the soldier and identity link. Nothing here commits.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import OidcRegistrationContext
from app.services.oidc_transactions import hash_secret

_PURGE_AFTER = timedelta(days=1)


def create_context(
    session: Session,
    *,
    issuer: str,
    subject: str,
    email: str,
    ad_username: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    """Store a context (superseding any unconsumed one for the subject); returns the cookie token."""
    now = now or datetime.now(timezone.utc)
    session.execute(
        delete(OidcRegistrationContext).where(
            (OidcRegistrationContext.expires_at < now - _PURGE_AFTER)
            | (
                (OidcRegistrationContext.issuer == issuer)
                & (OidcRegistrationContext.subject == subject)
                & OidcRegistrationContext.consumed_at.is_(None)
            )
        )
    )
    token = secrets.token_urlsafe(32)
    session.add(
        OidcRegistrationContext(
            token_hash=hash_secret(token),
            issuer=issuer,
            subject=subject,
            email=email,
            ad_username=ad_username,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    session.flush()
    return token


def get_active_context(
    session: Session, token: str | None, *, lock: bool = False, now: datetime | None = None
) -> OidcRegistrationContext | None:
    """The live (unconsumed, unexpired) context for this cookie token, else ``None``."""
    if not token:
        return None
    now = now or datetime.now(timezone.utc)
    query = select(OidcRegistrationContext).where(
        OidcRegistrationContext.token_hash == hash_secret(token),
        OidcRegistrationContext.consumed_at.is_(None),
        OidcRegistrationContext.expires_at > now,
    )
    if lock:
        query = query.with_for_update()
    return session.execute(query.execution_options(populate_existing=True)).scalar_one_or_none()


def consume_context(context: OidcRegistrationContext, *, now: datetime | None = None) -> None:
    context.consumed_at = now or datetime.now(timezone.utc)


REGISTRATION_COOKIE = "oidc_reg"
COLLISION_DETAILS = frozenset(
    {"email_taken", "ad_username_taken", "personal_number_taken", "personal_number already exists"}
)


class OidcRegistrationRefused(Exception):
    """The context can no longer be turned into a registration (shown generically)."""


def still_unmatched(session: Session, context: OidcRegistrationContext) -> bool:
    """Re-run identity resolution at the final step.

    Anything but ``NoMatch`` means the situation changed since the callback:
    an ambiguity is recorded as a ``registration`` conflict (the caller commits
    it) and the registration is refused.
    """
    from app.services.identity_resolution import (
        Ambiguous,
        Candidate,
        Match,
        record_identity_conflict,
        resolve_soldier_identity,
    )

    resolution = resolve_soldier_identity(session, context.email, context.ad_username)
    if isinstance(resolution, Ambiguous):
        candidates = resolution.as_candidates()
    elif isinstance(resolution, Match):
        candidates = [Candidate(resolution.soldier.id, ("email", "ad_username"))]
    else:
        return True
    record_identity_conflict(
        session, source="registration", ad_username=context.ad_username, candidates=candidates
    )
    return False


def bind_and_consume(session: Session, context: OidcRegistrationContext, soldier) -> None:
    """Link ``(issuer, subject)`` to the new soldier and spend the context.

    Runs in the registration transaction; on any failure the caller rolls back,
    leaving neither a soldier nor a link.
    """
    from sqlalchemy.exc import IntegrityError

    from app.db.models import OidcIdentity

    taken = session.execute(
        select(OidcIdentity.id).where(
            (OidcIdentity.soldier_id == soldier.id)
            | ((OidcIdentity.issuer == context.issuer) & (OidcIdentity.subject == context.subject))
        )
    ).first()
    if taken is not None:
        raise OidcRegistrationRefused("identity_already_linked")
    try:
        with session.begin_nested():
            session.add(OidcIdentity(soldier_id=soldier.id, issuer=context.issuer, subject=context.subject))
            session.flush()
    except IntegrityError as exc:
        raise OidcRegistrationRefused("identity_link_conflict") from exc
    consume_context(context)
    session.flush()
