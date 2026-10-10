"""The login limiter's own Redis connection is bounded and fails open."""
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import Response

from app import redis_client
from app.settings import get_settings


# app.rate_limit reads settings at import time, which must happen after the
# session fixtures point REDIS_URL at the test container, so import lazily.
def build_limiter(url):
    from app.rate_limit import build_limiter as factory

    return factory(url)


def test_limiter_storage_connection_carries_the_shared_socket_timeouts():
    from app.rate_limit import limiter

    kwargs = limiter._storage.storage.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == redis_client.SOCKET_TIMEOUT_SECONDS
    assert kwargs["socket_connect_timeout"] == redis_client.SOCKET_CONNECT_TIMEOUT_SECONDS


def test_factory_applies_timeouts_to_any_redis_url():
    built = build_limiter("redis://127.0.0.1:1/0")
    kwargs = built._storage.storage.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == redis_client.SOCKET_TIMEOUT_SECONDS
    assert kwargs["socket_connect_timeout"] == redis_client.SOCKET_CONNECT_TIMEOUT_SECONDS


def _request(path: str = "/x") -> Request:
    return Request({"type": "http", "client": ("9.9.9.9", 1), "headers": [], "path": path})


def test_unreachable_redis_does_not_take_the_endpoint_down_and_still_limits_in_process():
    dead = build_limiter("redis://127.0.0.1:1/0")

    @dead.limit("2/minute")
    def endpoint(request):
        return Response("ok")  # headers_enabled needs a real Response

    # Redis errors are swallowed (fail open) and an in-process fallback keeps
    # a per-process limit instead of no limit at all.
    assert endpoint(request=_request()).status_code == 200
    assert endpoint(request=_request()).status_code == 200
    try:
        endpoint(request=_request())
        limited = False
    except Exception as exc:
        limited = type(exc).__name__ == "RateLimitExceeded"
    assert limited


def test_default_key_func_is_remote_address():
    assert build_limiter(get_settings().redis_url)._key_func is get_remote_address
