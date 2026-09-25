from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_liveness_returns_alive(client: TestClient):
    r = client.get("/api/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "alive"}


def test_readiness_returns_ready_when_db_and_redis_are_up(client: TestClient):
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_readiness_returns_503_when_redis_is_down(client: TestClient, monkeypatch):
    import redis as redis_module

    from app import redis_client

    class _BrokenRedis:
        def ping(self):
            raise redis_module.ConnectionError("simulated outage")

    monkeypatch.setattr(redis_client, "get_redis", lambda: _BrokenRedis())
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"
