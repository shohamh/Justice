from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
