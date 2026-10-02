import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from app.db.models import ExemptionRequest, ExemptionRequestFile, Soldier
from app.file_authorization.policies import authorize_file
from app.file_authorization.schemas import FileAuthorizationRequest
from app.storage.keys import make_object_key


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def get(self, model, key):
        return self.rows.get((model, key))


def test_union_rejects_caller_selected_object_key():
    with pytest.raises(ValidationError):
        TypeAdapter(FileAuthorizationRequest).validate_python(
            {
                "kind": "exemption_request",
                "request_id": uuid.uuid4(),
                "file_id": uuid.uuid4(),
                "object_key": "private/file",
            }
        )


def test_request_owner_gets_metadata_for_exact_parent_file():
    actor_id, request_id, file_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    actor = SimpleNamespace(id=actor_id, left_at=None, role="soldier")
    parent = SimpleNamespace(id=request_id, soldier_id=actor_id)
    row = SimpleNamespace(
        id=file_id,
        exemption_request_id=request_id,
        storage_key=make_object_key("exemption_request", file_id),
        storage_sha256="a" * 64,
        storage_size=4,
        content_type="application/pdf",
        file_name="medical.pdf",
    )
    db = FakeSession(
        {
            (ExemptionRequestFile, file_id): row,
            (ExemptionRequest, request_id): parent,
            (Soldier, actor_id): actor,
        }
    )
    request = TypeAdapter(FileAuthorizationRequest).validate_python(
        {"kind": "exemption_request", "request_id": request_id, "file_id": file_id}
    )
    result = authorize_file(db, actor, request)
    assert result["object_key"] == f"exemption_request/{file_id}"
    assert result["filename"] == "medical.pdf"


def test_file_from_another_parent_is_not_found():
    actor_id, request_id, file_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    actor = SimpleNamespace(id=actor_id, left_at=None, role="soldier")
    row = SimpleNamespace(id=file_id, exemption_request_id=uuid.uuid4())
    db = FakeSession(
        {
            (ExemptionRequestFile, file_id): row,
            (ExemptionRequest, request_id): SimpleNamespace(id=request_id, soldier_id=actor_id),
        }
    )
    request = TypeAdapter(FileAuthorizationRequest).validate_python(
        {"kind": "exemption_request", "request_id": request_id, "file_id": file_id}
    )
    with pytest.raises(HTTPException) as exc:
        authorize_file(db, actor, request)
    assert exc.value.status_code == 404


def test_missing_storage_reference_fails_closed():
    actor_id, request_id, file_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    actor = SimpleNamespace(id=actor_id, left_at=None, role="soldier")
    db = FakeSession(
        {
            (ExemptionRequestFile, file_id): SimpleNamespace(
                id=file_id, exemption_request_id=request_id, storage_key=None
            ),
            (ExemptionRequest, request_id): SimpleNamespace(id=request_id, soldier_id=actor_id),
            (Soldier, actor_id): actor,
        }
    )
    request = TypeAdapter(FileAuthorizationRequest).validate_python(
        {"kind": "exemption_request", "request_id": request_id, "file_id": file_id}
    )
    with pytest.raises(HTTPException) as exc:
        authorize_file(db, actor, request)
    assert exc.value.status_code == 404
