"""Client error reports must not put URL secrets into structured logs."""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import get_optional_current_user
from app.routes.client_errors import router


def test_client_error_logging_scrubs_legacy_url_queries_and_fragments(caplog, monkeypatch):
    from app import error_logging

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_optional_current_user] = lambda: None
    client = TestClient(app)
    monkeypatch.setattr(error_logging, "_check_rate_limit", lambda _fingerprint: (True, 0))
    with caplog.at_level(logging.ERROR, logger="frontend.errors"):
        response = client.post(
            "/api/client-errors",
            json={
                "kind": "http-500",
                "message": "legacy URL scrub regression",
                "url": "https://justice.example/api/failure?token=query-secret#fragment-secret",
                "browser_url": "/reset-password?token=browser-secret",
                "filename": "https://justice.example/assets/app.js?token=filename-secret",
                "request_data": {"url": "/api/action?code=legacy-secret"},
            },
        )

    assert response.status_code == 204
    record = next(record for record in caplog.records if record.name == "frontend.errors")
    rendered = repr(record.frontend)
    assert "/api/failure" in rendered
    assert "/reset-password" in rendered
    assert "/assets/app.js" in rendered
    assert "/api/action" in rendered
    assert "query-secret" not in rendered
    assert "fragment-secret" not in rendered
    assert "browser-secret" not in rendered
    assert "filename-secret" not in rendered
    assert "legacy-secret" not in rendered
