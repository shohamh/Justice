from app.redis_client import get_redis


def test_get_redis_returns_working_client():
    client = get_redis()
    client.set("test_redis_client:ping", "pong")
    assert client.get("test_redis_client:ping") == "pong"


def test_get_redis_is_cached():
    assert get_redis() is get_redis()


def test_get_redis_bounds_socket_waits():
    """A hung Redis must not freeze refresh/logout/login (or any request) forever."""
    from app import redis_client

    kwargs = get_redis().connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == redis_client.SOCKET_TIMEOUT_SECONDS == 1
    assert kwargs["socket_connect_timeout"] == redis_client.SOCKET_CONNECT_TIMEOUT_SECONDS == 1
