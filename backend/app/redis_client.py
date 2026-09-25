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


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
