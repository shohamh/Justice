"""The whole point of this change: two independent Limiter instances backed
by the same Redis must share their counters, proving rate limits now work
across replicas/workers instead of being per-process."""
import limits
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.settings import get_settings


def _make_limiter() -> Limiter:
    return Limiter(key_func=get_remote_address, storage_uri=get_settings().redis_url)


def test_two_limiter_instances_share_redis_backed_counters():
    limiter_a = _make_limiter()
    limiter_b = _make_limiter()

    @limiter_a.limit("2/minute")
    def endpoint_a(request):
        return "ok"

    # slowapi's decorator requires an actual starlette.requests.Request (it
    # rejects a bare duck-typed stand-in), so build a minimal real one. A
    # fresh Request per call is required too — slowapi stashes
    # `_rate_limiting_complete` on `request.state` after the first check and
    # skips every subsequent check on that same request instance, which a
    # real HTTP client never reuses across requests.
    def _make_request() -> Request:
        scope = {"type": "http", "client": ("9.9.9.9", 1234), "headers": [], "path": "/endpoint-a"}
        return Request(scope)

    endpoint_a(request=_make_request())
    endpoint_a(request=_make_request())

    # A third call against limiter_a is over budget...
    try:
        endpoint_a(request=_make_request())
        raised = False
    except Exception:
        raised = True
    assert raised

    # ...and a fresh Limiter instance pointed at the same Redis key already
    # sees the same client as exhausted, which a MemoryStorage-backed
    # instance never would.
    #
    # get_window_stats takes a parsed RateLimitItem, not a bare string —
    # verified against the installed `limits` 5.8.0 by reading
    # limits/strategies.py: FixedWindowRateLimiter.get_window_stats calls
    # item.key_for(*identifiers) and item.amount, which a plain str doesn't
    # have. The identifiers themselves must match what slowapi actually hit
    # with: reading slowapi/extension.py's __evaluate_limits shows it hits
    # `[limit_key, limit_scope]`, where limit_scope defaults (key_style="url",
    # slowapi's own default) to the request path, confirmed by the
    # "exceeded at endpoint: /endpoint-a" warning slowapi logs above.
    item = limits.parse("2 per 1 minute")
    stats = limiter_b.limiter.get_window_stats(item, "9.9.9.9", "/endpoint-a")
    assert stats.remaining == 0
