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

# Every get_redis() caller issues short commands (GET/SET/EXISTS/DEL/pipelines/
# PING; no BLPOP, pub/sub or other long blocking reads), so a 1s bound per
# socket operation is ample. Without it a hung (not refused) Redis would block
# the calling thread indefinitely. With it, a stall raises redis.TimeoutError
# (a RedisError):
# - refresh-token revocation (app.auth.refresh_revocation) catches it and fails
#   open, so refresh/login/logout keep working;
# - the long-lived job cancel-flag poller (algorithm_bridge) logs and retries;
# - other request-path callers surface it as a 500.
# NOT covered: the slowapi rate limiter (app.rate_limit) opens its own storage
# connection from REDIS_URL, so login rate limiting has no such bound.
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
