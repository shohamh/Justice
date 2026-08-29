import json

from fastapi import Request
from fastapi.testclient import TestClient

from app.error_logging import redact, request_id


def test_request_id_rejects_header_injection_and_redacts_secrets():
    assert request_id("trace-123") == "trace-123"
    assert request_id("bad value\nforged") != "bad value\nforged"
    assert redact({"password": "hidden", "nested": {"access_token": "hidden"}, "ok": "yes"}) == {
        "password": "[redacted]", "nested": {"access_token": "[redacted]"}, "ok": "yes"
    }


def test_unhandled_http_exception_is_logged_with_request_context(monkeypatch):
    import app.main as main_module
    from app.main import create_app

    captured = {}

    def capture(request: Request, exc: BaseException, data: dict):
        captured.update(request_id=request.state.request_id, exception=str(exc), data=data)

    monkeypatch.setattr(main_module, "log_backend_exception", capture)
    app = create_app()

    @app.post("/test-error")
    async def test_error():
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/test-error?debug=yes",
        headers={"X-Request-ID": "trace-123", "Authorization": "Bearer secret"},
        json={"password": "secret", "name": "Shoham"},
    )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "trace-123"
    assert captured["exception"] == "boom"
    assert captured["data"]["query"] == {"debug": "yes"}
    assert captured["data"]["body"] == {"password": "[redacted]", "name": "Shoham"}
    assert "authorization" not in json.dumps(captured["data"]).lower()


def test_frontend_error_endpoint_writes_to_dedicated_logger(monkeypatch):
    import app.routes.client_errors as client_errors
    from app.main import create_app

    records = []
    monkeypatch.setattr(client_errors, "log_frontend_error", records.append)
    response = TestClient(create_app()).post(
        "/api/client-errors",
        json={"request_id": "trace-1", "kind": "http-500", "message": "failed", "request_data": {"token": "x"}},
    )
    assert response.status_code == 204
    assert records[0]["request_id"] == "trace-1"
