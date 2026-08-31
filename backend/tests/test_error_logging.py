import json
import logging
from types import SimpleNamespace

from fastapi import Request
from fastapi.testclient import TestClient

from app import error_logging as error_logging_module
from app.error_logging import log_backend_exception, log_frontend_error, redact, request_id


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


def test_unhandled_http_exception_carries_user_and_ip(monkeypatch):
    import app.main as main_module
    from app.main import create_app

    captured = {}

    def capture(request: Request, exc: BaseException, data: dict):
        captured.update(data=data, user=getattr(request.state, "user", None), ip=request.client.host if request.client else None)

    monkeypatch.setattr(main_module, "log_backend_exception", capture)
    app = create_app()
    user = SimpleNamespace(id="soldier-1", full_name="Shoham")

    @app.post("/test-error-with-user")
    async def test_error_with_user(request: Request):
        request.state.user = user
        raise RuntimeError("boom")

    response = TestClient(app, raise_server_exceptions=False).post("/test-error-with-user")

    assert response.status_code == 500
    assert captured["user"] is user
    assert captured["ip"] == "testclient"


def test_frontend_error_endpoint_writes_to_dedicated_logger(monkeypatch):
    import app.routes.client_errors as client_errors
    from app.auth.deps import get_optional_current_user
    from app.main import create_app

    records = []
    monkeypatch.setattr(client_errors, "log_frontend_error", lambda payload, **kwargs: records.append((payload, kwargs)))
    app = create_app()
    app.dependency_overrides[get_optional_current_user] = lambda: None
    response = TestClient(app).post(
        "/api/client-errors",
        json={"request_id": "trace-1", "kind": "http-500", "message": "failed", "request_data": {"token": "x"}},
    )
    assert response.status_code == 204
    assert records[0][0]["request_id"] == "trace-1"


def test_frontend_error_endpoint_passes_user_and_ip_to_logger(monkeypatch):
    import app.routes.client_errors as client_errors
    from app.auth.deps import get_optional_current_user
    from app.main import create_app

    records = []
    monkeypatch.setattr(client_errors, "log_frontend_error", lambda payload, **kwargs: records.append((payload, kwargs)))
    app = create_app()
    app.dependency_overrides[get_optional_current_user] = lambda: SimpleNamespace(id="soldier-1", full_name="Shoham")

    response = TestClient(app).post(
        "/api/client-errors",
        json={"request_id": "trace-2", "kind": "uncaught-error", "message": "failed"},
    )

    assert response.status_code == 204
    assert records[0][0]["request_id"] == "trace-2"
    assert records[0][1]["user"].full_name == "Shoham"
    assert records[0][1]["ip"] == "testclient"


class _RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _capture(logger_name: str):
    logger = logging.getLogger(logger_name)
    handler = _RecordingHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    return handler, logger


class _FakeRateLimitSettings:
    error_log_rate_limit_max_per_window = 3
    error_log_rate_limit_window_seconds = 60.0


class _FakeRequestState:
    request_id = "r1"


class _FakeRequest:
    state = _FakeRequestState()


def _setup_rate_limit_test(monkeypatch):
    error_logging_module._rate_limit_state.clear()
    monkeypatch.setattr("app.settings.get_settings", lambda: _FakeRateLimitSettings())
    fake_time = {"now": 1000.0}
    monkeypatch.setattr(error_logging_module.time, "monotonic", lambda: fake_time["now"])
    return fake_time


def test_repeated_frontend_errors_are_rate_limited_per_fingerprint(monkeypatch):
    _setup_rate_limit_test(monkeypatch)
    handler, logger = _capture("frontend.errors")
    try:
        payload = {"request_id": "r1", "kind": "uncaught-error", "message": "boom", "filename": "x.ts", "line": 1}
        for _ in range(10):
            log_frontend_error(payload)
        # Capped at the configured max (3 here) even though called 10 times.
        assert len(handler.records) == 3
        assert all(r.getMessage() == "Frontend error" for r in handler.records)

        # A different fingerprint isn't affected by the first one's cap.
        log_frontend_error({**payload, "message": "a different error"})
        assert len(handler.records) == 4
    finally:
        logger.removeHandler(handler)


def test_rate_limit_window_rollover_emits_one_rollup_line(monkeypatch):
    fake_time = _setup_rate_limit_test(monkeypatch)
    handler, logger = _capture("frontend.errors")
    try:
        payload = {"request_id": "r1", "kind": "uncaught-error", "message": "boom", "filename": "x.ts", "line": 1}
        for _ in range(10):
            log_frontend_error(payload)
        assert len(handler.records) == 3  # 3 logged, 7 suppressed

        fake_time["now"] += 61  # past the 60s window
        log_frontend_error(payload)

        assert len(handler.records) == 5
        rollup, resumed = handler.records[-2], handler.records[-1]
        assert rollup.getMessage() == "Frontend error (rate-limit rollup)"
        assert rollup.suppressed_count == 7
        assert resumed.getMessage() == "Frontend error"
    finally:
        logger.removeHandler(handler)


def test_repeated_backend_exceptions_are_rate_limited_per_fingerprint(monkeypatch):
    _setup_rate_limit_test(monkeypatch)
    handler, logger = _capture("backend.errors")
    try:
        for _ in range(10):
            log_backend_exception(_FakeRequest(), RuntimeError("boom"), {"path": "/broken"})
        assert len(handler.records) == 3

        # A different exception/path is a different fingerprint, unaffected.
        log_backend_exception(_FakeRequest(), RuntimeError("boom"), {"path": "/other"})
        assert len(handler.records) == 4
    finally:
        logger.removeHandler(handler)
