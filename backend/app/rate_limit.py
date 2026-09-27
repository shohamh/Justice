from slowapi import Limiter
from slowapi.util import get_remote_address

from app.settings import get_settings

# headers_enabled: slowapi's default RateLimitExceeded handler only sets
# Retry-After when this is on; without it, the header is silently omitted
# and the frontend has no way to display a real countdown.
#
# storage_uri=Redis: without this, `limits` defaults to an in-process
# MemoryStorage, so rate limits only apply per-process — a second uvicorn
# worker or a second replica gets its own independent counters and the
# limit effectively multiplies by however many processes are running.
limiter = Limiter(
    key_func=get_remote_address, headers_enabled=True, storage_uri=get_settings().redis_url,
)
