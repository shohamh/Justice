"""Decide what a validated OIDC identity may do in Justice.

``authenticate`` maps ``(issuer, subject)`` to a soldier:

* a linked subject logs in as its soldier (if still active) whatever email the
  provider now asserts;
* otherwise :func:`~app.services.identity_resolution.resolve_soldier_identity`
  decides: ``Match`` links the subject (inactive or already-linked soldiers are
  denied), ``Ambiguous`` records an ``IdentityConflict`` (source ``sso``) and
  is denied, ``NoMatch`` is handed to registration (``kind == "no_match"``).

Results carry only an internal reason code for audit; callers show every denial
identically. The function commits nothing except what it must persist even on
denial (the conflict), via the caller's commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import OidcIdentity, Soldier
from app.services.identity import canonical_identity
from app.services.identity_resolution import (
    Ambiguous,
    Match,
    NoMatch,
    record_identity_conflict,
    resolve_soldier_identity,
)
from app.services.oidc import VerifiedIdentity


@dataclass(frozen=True)
class SsoResult:
    kind: Literal["login", "denied", "no_match"]
    soldier: Soldier | None = None
    reason: str = ""
    email: str | None = None
    ad_username: str | None = None
    linked: bool = False


def _denied(reason: str) -> SsoResult:
    return SsoResult("denied", reason=reason)


def _linked_identity(session: Session, issuer: str, subject: str) -> OidcIdentity | None:
    return session.execute(
        select(OidcIdentity).where(OidcIdentity.issuer == issuer, OidcIdentity.subject == subject)
    ).scalar_one_or_none()


def _login(session: Session, identity: OidcIdentity, *, linked: bool = False) -> SsoResult:
    soldier = session.get(Soldier, identity.soldier_id)
    if soldier is None or soldier.left_at is not None:
        return _denied("soldier_inactive")
    identity.last_login_at = datetime.now(timezone.utc)
    return SsoResult("login", soldier=soldier, linked=linked)


def authenticate(session: Session, verified: VerifiedIdentity) -> SsoResult:
    existing = _linked_identity(session, verified.issuer, verified.subject)
    if existing is not None:
        return _login(session, existing)

    try:
        email, ad_username = canonical_identity(verified.email)
    except ValueError:
        return _denied("email_unsupported")
    if email is None or ad_username is None:
        return _denied("email_unsupported")

    resolution = resolve_soldier_identity(session, email, ad_username)
    if isinstance(resolution, Ambiguous):
        record_identity_conflict(
            session, source="sso", ad_username=ad_username, candidates=resolution.as_candidates()
        )
        return _denied("ambiguous")
    if isinstance(resolution, NoMatch):
        return SsoResult("no_match", email=email, ad_username=ad_username)

    assert isinstance(resolution, Match)
    soldier = resolution.soldier
    if soldier.left_at is not None:
        return _denied("soldier_inactive")
    taken = session.execute(
        select(OidcIdentity.id).where(OidcIdentity.soldier_id == soldier.id)
    ).first()
    if taken is not None:
        # Either linked to another subject, or a concurrent login of this very
        # subject committed between our lookup and now.
        winner = _linked_identity(session, verified.issuer, verified.subject)
        if winner is not None and winner.soldier_id == soldier.id:
            return _login(session, winner)
        return _denied("soldier_already_linked")

    identity = OidcIdentity(soldier_id=soldier.id, issuer=verified.issuer, subject=verified.subject)
    try:
        with session.begin_nested():
            session.add(identity)
            session.flush()
    except IntegrityError:
        # A concurrent first login won the race; accept it only if it is the same pairing.
        session.expire_all()
        winner = _linked_identity(session, verified.issuer, verified.subject)
        if winner is not None and winner.soldier_id == soldier.id:
            return _login(session, winner)
        return _denied("link_conflict")
    return _login(session, identity, linked=True)
