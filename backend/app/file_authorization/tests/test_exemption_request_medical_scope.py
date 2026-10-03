import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.file_authorization.policies as policies
from app.db.models import ExemptionRequest, ExemptionRequestFile, Soldier
from app.file_authorization.schemas import ExemptionRequestFileRequest
from app.storage.keys import make_object_key


class DB:
    def __init__(self, *rows):
        self.rows = {(kind, key): value for kind, key, value in rows}

    def get(self, kind, key):
        return self.rows.get((kind, key))


def test_exemption_request_allows_current_medical_viewer_and_denies_without_scope(monkeypatch):
    soldier_id, request_id, file_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    viewer = SimpleNamespace(id=uuid.uuid4(), left_at=None, must_change_password=False)
    target = SimpleNamespace(id=soldier_id, left_at=None)
    parent = SimpleNamespace(id=request_id, soldier_id=soldier_id)
    row = SimpleNamespace(
        id=file_id,
        exemption_request_id=request_id,
        storage_key=make_object_key("exemption_request", file_id),
        storage_sha256="a" * 64,
        storage_size=7,
        content_type="application/pdf",
        file_name="medical.pdf",
    )
    db = DB(
        (ExemptionRequestFile, file_id, row),
        (ExemptionRequest, request_id, parent),
        (Soldier, soldier_id, target),
    )
    request = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=request_id, file_id=file_id
    )
    checks = []
    monkeypatch.setattr(
        policies,
        "can_view_medical_document",
        lambda session, actor, soldier: checks.append((actor.id, soldier.id)) or True,
    )
    assert policies.authorize_file(db, viewer, request)["object_key"] == (
        f"exemption_request/{file_id}"
    )
    assert checks == [(viewer.id, soldier_id)]

    monkeypatch.setattr(policies, "can_view_medical_document", lambda *args: False)
    with pytest.raises(HTTPException) as exc:
        policies.authorize_file(db, viewer, request)
    assert exc.value.status_code == 403
