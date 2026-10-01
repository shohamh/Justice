import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.file_authorization.main as authorization
from app.auth import deps as auth_deps
from app.auth.jwt_tokens import InvalidToken
from app.db.models import BugReport, Soldier
from app.db.session import get_session
from app.storage.keys import make_object_key


class FakeSession:
    def __init__(self, rows=None):
        self.entries = []
        self.commits = 0
        self.rows = rows or {}

    def get(self, model, row_id):
        return self.rows.get((model, row_id))

    def add(self, row):
        self.entries.append(row)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_invalid_bearer_is_audited_without_sensitive_context(monkeypatch):
    app = authorization.create_app()
    db = FakeSession()
    app.dependency_overrides[get_session] = lambda: db

    def invalid(*args, **kwargs):
        raise HTTPException(401, detail="invalid_token")

    monkeypatch.setattr(authorization, "get_current_user", invalid)
    request_id = str(uuid.uuid4())
    response = TestClient(app).post(
        "/_internal/file-authorizations",
        headers={"Authorization": "Bearer invalid", "X-Request-ID": request_id},
        json={
            "kind": "exemption_request",
            "request_id": str(uuid.uuid4()),
            "file_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 401
    entry = db.entries[0]
    assert entry.action == "file.download.deny" and entry.actor_id is None
    assert set(entry.context) == {"file_class", "request_id"}
    assert entry.context["request_id"] == request_id
    assert db.commits == 1


def _screenshot_request(report_id):
    return {
        "kind": "bug_report_screenshot",
        "report_id": str(report_id),
    }


def _user(user_id, *, left_at=None):
    return SimpleNamespace(
        id=user_id,
        left_at=left_at,
        must_change_password=False,
        role="soldier",
    )


def _report(report_id, reporter_id):
    return SimpleNamespace(
        id=report_id,
        reporter_id=reporter_id,
        storage_key=make_object_key("bug_report_screenshot", report_id),
        storage_sha256="a" * 64,
        storage_size=12,
        file_name="report.png",
    )


def _token_claims(monkeypatch, claims_by_token):
    def decode(token):
        claims = claims_by_token.get(token)
        if isinstance(claims, Exception):
            raise claims
        return claims

    monkeypatch.setattr(auth_deps, "decode_token", decode)


def test_file_authorization_allows_the_reporter_and_audits_the_resolved_actor(monkeypatch):
    reporter_id, report_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = FakeSession(
        {
            (Soldier, reporter_id): _user(reporter_id),
            (BugReport, report_id): _report(report_id, reporter_id),
        }
    )
    app = authorization.create_app()
    app.dependency_overrides[get_session] = lambda: db
    _token_claims(
        monkeypatch,
        {"synthetic-owner-token": {"type": "access", "sub": str(reporter_id)}},
    )

    response = TestClient(app).post(
        "/_internal/file-authorizations",
        headers={
            "Authorization": "Bearer synthetic-owner-token",
            "X-Request-ID": str(request_id),
        },
        json=_screenshot_request(report_id),
    )

    assert response.status_code == 200
    assert response.json()["object_key"] == f"bug_report_screenshot/{report_id}"
    entry = db.entries[0]
    assert entry.actor_id == reporter_id and entry.action == "file.download.allow"
    assert set(entry.context) == {"file_class", "request_id"}
    assert db.commits == 1


def test_file_authorization_denies_a_different_active_identity_without_metadata(monkeypatch):
    owner_id, other_id, report_id, request_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    db = FakeSession(
        {
            (Soldier, owner_id): _user(owner_id),
            (Soldier, other_id): _user(other_id),
            (BugReport, report_id): _report(report_id, owner_id),
        }
    )
    app = authorization.create_app()
    app.dependency_overrides[get_session] = lambda: db
    _token_claims(
        monkeypatch,
        {"synthetic-other-token": {"type": "access", "sub": str(other_id)}},
    )

    response = TestClient(app).post(
        "/_internal/file-authorizations",
        headers={
            "Authorization": "Bearer synthetic-other-token",
            "X-Request-ID": str(request_id),
        },
        json=_screenshot_request(report_id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "file_download_forbidden"}
    entry = db.entries[0]
    assert entry.actor_id == other_id and entry.action == "file.download.deny"
    assert set(entry.context) == {"file_class", "request_id"}
    assert db.commits == 1


def test_file_authorization_rejects_departed_identity_without_disclosing_resource(monkeypatch):
    departed_id, report_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = FakeSession(
        {
            (Soldier, departed_id): _user(departed_id, left_at=object()),
            (BugReport, report_id): _report(report_id, departed_id),
        }
    )
    app = authorization.create_app()
    app.dependency_overrides[get_session] = lambda: db
    _token_claims(
        monkeypatch,
        {"synthetic-departed-token": {"type": "access", "sub": str(departed_id)}},
    )

    response = TestClient(app).post(
        "/_internal/file-authorizations",
        headers={
            "Authorization": "Bearer synthetic-departed-token",
            "X-Request-ID": str(request_id),
        },
        json=_screenshot_request(report_id),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "user_not_found"}
    entry = db.entries[0]
    assert entry.actor_id is None and entry.action == "file.download.deny"
    assert set(entry.context) == {"file_class", "request_id"}
    assert db.commits == 1


def test_file_authorization_rejects_stale_token_without_disclosing_resource(monkeypatch):
    report_id, request_id = uuid.uuid4(), uuid.uuid4()
    db = FakeSession()
    app = authorization.create_app()
    app.dependency_overrides[get_session] = lambda: db
    _token_claims(monkeypatch, {"synthetic-expired-token": InvalidToken("expired")})

    response = TestClient(app).post(
        "/_internal/file-authorizations",
        headers={
            "Authorization": "Bearer synthetic-expired-token",
            "X-Request-ID": str(request_id),
        },
        json=_screenshot_request(report_id),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_token"}
    entry = db.entries[0]
    assert entry.actor_id is None and entry.action == "file.download.deny"
    assert set(entry.context) == {"file_class", "request_id"}
    assert db.commits == 1
