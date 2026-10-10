"""Server-side, single-use, browser-bound OIDC login transactions.

``begin_transaction`` creates the authorization request and persists its
secrets (nonce, PKCE verifier) keyed by the *hash* of the state; the browser
receives a random cookie token whose hash is stored as the binding.
``consume_transaction`` redeems it exactly once: a single ``UPDATE ... WHERE
consumed_at IS NULL AND expires_at > now RETURNING`` makes concurrent callbacks
race safely, and a callback from a different browser burns the transaction
instead of leaving it replayable. Neither function commits.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.db.models import OidcTransaction
from app.services.oidc import AuthorizationRequest, OidcClient, OidcError

_PURGE_AFTER = timedelta(days=1)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class ConsumedTransaction:
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)
    # The login page's "remember me" choice, taken from the verified browser token.
    remember: bool = True


# The choice rides inside the browser cookie token. Only its hash is stored, and the
# callback compares that hash before reading the prefix, so a browser cannot flip the
# choice by editing the cookie (the edited token would not match the stored hash).
_REMEMBER_PREFIX = "r1."
_SESSION_PREFIX = "r0."


def begin_transaction(
    session: Session, client: OidcClient, *, now: datetime | None = None, remember: bool = True
) -> tuple[AuthorizationRequest, str]:
    """Start a login; returns the authorization request and the browser cookie token.

    ``remember=False`` (login page "remember me" unticked) is bound into the token.
    """
    now = now or datetime.now(timezone.utc)
    request = client.start()
    browser_token = (_REMEMBER_PREFIX if remember else _SESSION_PREFIX) + secrets.token_urlsafe(32)
    session.execute(delete(OidcTransaction).where(OidcTransaction.expires_at < now - _PURGE_AFTER))
    session.add(
        OidcTransaction(
            state_hash=hash_secret(request.state),
            browser_hash=hash_secret(browser_token),
            nonce=request.nonce,
            code_verifier=request.code_verifier,
            expires_at=now + timedelta(seconds=client.config.transaction_ttl_seconds),
        )
    )
    session.flush()
    return request, browser_token


def consume_transaction(
    session: Session, *, state: str | None, browser_token: str | None, now: datetime | None = None
) -> ConsumedTransaction:
    """Redeem a transaction once; raises ``OidcError`` for any invalid use."""
    if not state:
        raise OidcError("transaction_invalid")
    now = now or datetime.now(timezone.utc)
    row = session.execute(
        update(OidcTransaction)
        .where(
            OidcTransaction.state_hash == hash_secret(state),
            OidcTransaction.consumed_at.is_(None),
            OidcTransaction.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(OidcTransaction.browser_hash, OidcTransaction.nonce, OidcTransaction.code_verifier)
    ).first()
    if row is None:
        raise OidcError("transaction_invalid")
    browser_hash, nonce, code_verifier = row
    if not browser_token or not hmac.compare_digest(browser_hash, hash_secret(browser_token)):
        raise OidcError("browser_mismatch")
    return ConsumedTransaction(
        nonce=nonce,
        code_verifier=code_verifier,
        remember=not browser_token.startswith(_SESSION_PREFIX),
    )
