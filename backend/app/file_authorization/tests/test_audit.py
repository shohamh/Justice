import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.file_authorization.main as authorization
from app.db.session import get_session


class FakeSession:
    def __init__(self):
        self.entries = []
        self.commits = 0

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
