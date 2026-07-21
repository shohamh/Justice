from slowapi import Limiter
from slowapi.util import get_remote_address

# headers_enabled: slowapi's default RateLimitExceeded handler only sets
# Retry-After when this is on; without it, the header is silently omitted
# and the frontend has no way to display a real countdown.
limiter = Limiter(key_func=get_remote_address, headers_enabled=True)
