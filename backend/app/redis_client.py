"""Shared Redis client factory.

One process-wide client (redis-py pools connections internally, so this is
not "one connection" — it's the same singleton-factory pattern as
app.settings.get_settings()). Every piece of state that used to live in a
module-level dict/Event goes through this so it's visible across replicas
and worker processes instead of being pinned to whichever one happened to
handle a given request.
"""
from __future__ import annotations

from functools import lru_cache

import redis

from app.settings import get_settings

# Every caller issues short commands (GET/SET/EXISTS/DEL/pipelines/PING; no
# BLPOP, pub/sub or other long blocking reads), so a 1s bound per socket
# operation is ample. Without it a hung (not refused) Redis would block the
# request thread indefinitely -- refresh, login and logout included. A timeout
# raises redis.TimeoutError (a RedisError), which the callers already handle
# (e.g. app.auth.refresh_revocation fails open).
SOCKET_TIMEOUT_SECONDS = 1
SOCKET_CONNECT_TIMEOUT_SECONDS = 1


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=SOCKET_CONNECT_TIMEOUT_SECONDS,
    )
