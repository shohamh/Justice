import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import AdminErrorClear
from app.settings import get_settings
from tests.helpers import auth_headers, create_soldier

LOKI = "http://loki.test:3100"
QUERY_RANGE = f"{LOKI}/loki/api/v1/query_range"

OLD_ENTRY = {"ts": "2026-01-01T00:00:00+00:00", "level": "ERROR", "msg": "old", "logger": "backend.errors"}
AT_CUTOFF_ENTRY = {"ts": "2026-03-01T00:00:00+00:00", "level": "ERROR", "msg": "at-cutoff", "logger": "backend.errors"}
NEW_ENTRY = {"ts": "2026-06-01T00:00:00+00:00", "level": "ERROR", "msg": "new", "logger": "frontend.errors"}
CUTOFF = datetime(2026, 3, 1, tzinfo=UTC)


def _loki_response(*records: dict) -> dict:
    return {
        "data": {
            "result": [
                {"stream": {"app": "justice-backend", "log_type": "errors"}, "values": [[str(i), json.dumps(r)] for i, r in enumerate(records)]}
            ]
        }
    }


@pytest.fixture()
def loki_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("LOKI_URL", LOKI)
    get_settings.cache_clear()
    try:
        yield LOKI
    finally:
        monkeypatch.delenv("LOKI_URL", raising=False)
        get_settings.cache_clear()


@pytest.fixture()
def loki(loki_url: str) -> Iterator[respx.Router]:
    with respx.mock(assert_all_called=False) as router:
        router.get(QUERY_RANGE).mock(
            return_value=httpx.Response(200, json=_loki_response(OLD_ENTRY, AT_CUTOFF_ENTRY, NEW_ENTRY))
        )
        yield router


def _admin(session: Session, personal_number: str):
    admin = create_soldier(session, personal_number=personal_number, role="admin")
    session.commit()
    return admin


def _messages(client: TestClient, headers: dict[str, str], **params) -> list[str]:
    response = client.get("/api/admin/errors", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return [item["message"] for item in response.json()["items"]]


def test_clear_admin_errors_hides_entries_at_or_before_cutoff_for_that_admin_only(
    client: TestClient, admin_session: Session, loki: respx.Router,
):
    clearing_admin = _admin(admin_session, "errors-admin-1")
    other_admin = _admin(admin_session, "errors-admin-2")

    clear_response = client.delete(
        "/api/admin/errors", headers=auth_headers(clearing_admin), params={"through": CUTOFF.isoformat()},
    )
    assert clear_response.status_code == 200
    assert clear_response.json() == {"status": "cleared"}

    assert _messages(client, auth_headers(clearing_admin)) == ["new"]
    # Soft clear is per admin, and never deletes the underlying log data.
    assert _messages(client, auth_headers(other_admin)) == ["new", "at-cutoff", "old"]


def test_clear_admin_errors_also_hides_entries_from_unread_count(
    client: TestClient, admin_session: Session, loki: respx.Router,
):
    admin = _admin(admin_session, "errors-admin-count")
    headers = auth_headers(admin)
    assert client.get("/api/admin/errors/unread-count", headers=headers).json() == {"count": 3}

    client.delete("/api/admin/errors", headers=headers, params={"through": CUTOFF.isoformat()})

    assert client.get("/api/admin/errors/unread-count", headers=headers).json() == {"count": 1}


def test_explicit_from_filter_cannot_reveal_cleared_entries(
    client: TestClient, admin_session: Session, loki: respx.Router,
):
    admin = _admin(admin_session, "errors-admin-from")
    headers = auth_headers(admin)
    client.delete("/api/admin/errors", headers=headers, params={"through": CUTOFF.isoformat()})

    assert _messages(client, headers, **{"from": "2025-01-01T00:00:00+00:00"}) == ["new"]


def test_mark_all_read_skips_cleared_entries(
    client: TestClient, admin_session: Session, loki: respx.Router,
):
    admin = _admin(admin_session, "errors-admin-mark-all")
    headers = auth_headers(admin)
    client.delete("/api/admin/errors", headers=headers, params={"through": CUTOFF.isoformat()})

    response = client.post("/api/admin/errors/mark-all-read", headers=headers)
    assert response.status_code == 204

    items = client.get("/api/admin/errors", headers=headers).json()["items"]
    assert [(item["message"], item["unread"]) for item in items] == [("new", False)]


def test_clear_cursor_never_moves_backwards(
    client: TestClient, admin_session: Session, loki: respx.Router,
):
    admin = _admin(admin_session, "errors-admin-monotonic")
    headers = auth_headers(admin)
    client.delete("/api/admin/errors", headers=headers, params={"through": CUTOFF.isoformat()})
    client.delete("/api/admin/errors", headers=headers, params={"through": "2025-01-01T00:00:00+00:00"})

    admin_session.expire_all()
    assert admin_session.get(AdminErrorClear, admin.id).cleared_before == CUTOFF
    assert _messages(client, headers) == ["new"]


def test_clear_through_a_future_time_does_not_hide_errors_that_have_not_happened_yet(
    client: TestClient, admin_session: Session, loki: respx.Router,
):
    admin = _admin(admin_session, "errors-admin-future")
    before = datetime.now(UTC)

    client.delete(
        "/api/admin/errors", headers=auth_headers(admin),
        params={"through": (before + timedelta(days=365)).isoformat()},
    )

    admin_session.expire_all()
    cursor = admin_session.get(AdminErrorClear, admin.id).cleared_before
    assert before <= cursor <= datetime.now(UTC)


def test_admin_errors_endpoints_require_admin(client: TestClient, admin_session: Session, loki: respx.Router):
    soldier = create_soldier(admin_session, personal_number="errors-plain")
    admin_session.commit()
    headers = auth_headers(soldier)

    assert client.get("/api/admin/errors", headers=headers).status_code == 403
    assert client.delete("/api/admin/errors", headers=headers, params={"through": CUTOFF.isoformat()}).status_code == 403


def test_admin_errors_returns_503_when_loki_is_unreachable(
    client: TestClient, admin_session: Session, loki_url: str,
):
    admin = _admin(admin_session, "errors-admin-loki-down")
    with respx.mock(assert_all_called=False) as router:
        router.get(QUERY_RANGE).mock(side_effect=httpx.ConnectError("connection refused"))
        response = client.get("/api/admin/errors", headers=auth_headers(admin))

    assert response.status_code == 503


def test_admin_errors_is_empty_when_loki_is_not_configured(
    client: TestClient, admin_session: Session, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("LOKI_URL", raising=False)
    get_settings.cache_clear()
    admin = _admin(admin_session, "errors-admin-no-loki")
    try:
        response = client.get("/api/admin/errors", headers=auth_headers(admin))
        count = client.get("/api/admin/errors/unread-count", headers=auth_headers(admin))
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}
    assert count.json() == {"count": 0}
