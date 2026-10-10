from slowapi import Limiter
from slowapi.util import get_remote_address

from app.redis_client import SOCKET_CONNECT_TIMEOUT_SECONDS, SOCKET_TIMEOUT_SECONDS
from app.settings import get_settings


def build_limiter(redis_url: str) -> Limiter:
    """Build the rate limiter backed by the Redis at ``redis_url``.

    headers_enabled: slowapi's default RateLimitExceeded handler only sets
    Retry-After when this is on; without it, the header is silently omitted
    and the frontend has no way to display a real countdown.

    storage_uri=Redis: without this, `limits` defaults to an in-process
    MemoryStorage, so rate limits only apply per-process -- a second uvicorn
    worker or a second replica gets its own independent counters and the
    limit effectively multiplies by however many processes are running.

    storage_options: the limiter opens its own Redis connection, so the shared
    client's socket timeouts (app.redis_client) do not cover it. Reuse the same
    bounds so a hung Redis cannot stall /login for longer than they allow.

    Redis outage: swallow_errors + in_memory_fallback_enabled. A Redis error
    must not turn into a 500 on /login (before this, the default
    swallow_errors=False raised). slowapi falls back to a per-process
    in-memory limit and re-checks Redis periodically, so the limit is weaker
    (per worker) but still present during the outage. The per-account login
    lockout lives in the database and is unaffected.
    """
    return Limiter(
        key_func=get_remote_address,
        headers_enabled=True,
        storage_uri=redis_url,
        storage_options={
            "socket_timeout": SOCKET_TIMEOUT_SECONDS,
            "socket_connect_timeout": SOCKET_CONNECT_TIMEOUT_SECONDS,
        },
        swallow_errors=True,
        in_memory_fallback_enabled=True,
    )


limiter = build_limiter(get_settings().redis_url)
