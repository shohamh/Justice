"""Per-session refresh-token revocation (logout).

Refresh tokens are stateless JWTs. Bumping ``Soldier.token_version`` revokes
*every* session of a user, which is wrong for a plain logout on one device.
Instead, logout records the presented token's identifiers here and
``/auth/refresh`` rejects them:

- ``jti`` -- the exact token presented at logout. TTL = the token's remaining
  lifetime (capped at ``refresh_token_days``); after that the JWT is expired
  anyway, so the key can go.
- ``sid`` -- the login session the token belongs to (inherited on rotation).
  A refresh processed just *before* the logout rotates C1 -> C2, and its
  response can still reach the browser after logout deleted the cookie; C2 has
  a new jti but the same sid, so it is rejected too. Any token in that family
  was issued no later than ~now and lives at most ``refresh_token_days``, so the
  sid key lives ``refresh_token_days`` plus a small margin.

Store: Redis -- the same store the login rate limiter (app.rate_limit) and the
other cross-replica state (app.redis_client) already require, so no new
infrastructure and native TTL expiry.

Failure policy (both directions deliberately lenient, see the batch-3 report):
- ``is_revoked`` fails OPEN: if Redis is unreachable the refresh is allowed
  and a warning is logged. That is exactly the pre-revocation behaviour, so an
  outage cannot lock every user out.
- ``revoke`` never raises: logout still deletes the cookie and returns ok.

Tokens issued before ``jti``/``sid`` existed carry neither claim; they cannot be
revoked individually and stay valid until expiry (or a token_version bump).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

import redis

from app.redis_client import get_redis
from app.settings import get_settings

_logger = logging.getLogger("app.auth")

_PREFIX = "auth:refresh:revoked:"
# Slack on the session-family TTL for clock skew between replicas and a
# rotation that was already past its revocation check when logout landed.
SESSION_TTL_MARGIN_SECONDS = 300


def _claim(payload: Mapping[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if isinstance(value, str) and value:
        return value
    return None


def _jti_key(jti: str) -> str:
    return f"{_PREFIX}jti:{jti}"


def _sid_key(sid: str) -> str:
    return f"{_PREFIX}sid:{sid}"


def revoke(payload: Mapping[str, Any]) -> None:
    """Revoke the token (jti) and its login session (sid). Never raises."""
    jti = _claim(payload, "jti")
    sid = _claim(payload, "sid")
    if jti is None and sid is None:
        return  # legacy token: nothing to key on
    max_lifetime = get_settings().refresh_token_days * 24 * 3600
    try:
        exp = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        exp = 0
    remaining = exp - int(time.time())
    jti_ttl = max(1, min(remaining, max_lifetime)) if remaining > 0 else max_lifetime
    try:
        pipe = get_redis().pipeline(transaction=False)
        if jti is not None:
            pipe.set(_jti_key(jti), "1", ex=jti_ttl)
        if sid is not None:
            pipe.set(_sid_key(sid), "1", ex=max_lifetime + SESSION_TTL_MARGIN_SECONDS)
        pipe.execute()
    except redis.RedisError:
        _logger.warning(
            "refresh-token revocation store unavailable at logout; the presented "
            "refresh token stays valid until it expires",
            exc_info=True,
        )


def is_revoked(payload: Mapping[str, Any]) -> bool:
    """True when the token's jti or sid was revoked. Fails open (False) on store errors."""
    jti = _claim(payload, "jti")
    sid = _claim(payload, "sid")
    keys = []
    if jti is not None:
        keys.append(_jti_key(jti))
    if sid is not None:
        keys.append(_sid_key(sid))
    if not keys:
        return False
    try:
        return bool(get_redis().exists(*keys))
    except redis.RedisError:
        _logger.warning(
            "refresh-token revocation store unavailable at refresh; failing open",
            exc_info=True,
        )
        return False
