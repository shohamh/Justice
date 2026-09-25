from app.redis_client import get_redis


def test_get_redis_returns_working_client():
    client = get_redis()
    client.set("test_redis_client:ping", "pong")
    assert client.get("test_redis_client:ping") == "pong"


def test_get_redis_is_cached():
    assert get_redis() is get_redis()
