from fastapi.testclient import TestClient


def test_metrics_endpoint_exposes_prometheus_format(client: TestClient):
    # Generate at least one request for the instrumentator to have something
    # to report.
    client.get("/api/health")

    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "http_requests_total" in r.text
