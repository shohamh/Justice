from __future__ import annotations

import hashlib
import uuid

import pytest

from app.db.models import (
    ExemptionRequest,
    ExemptionRequestFile,
    ExemptionType,
    SoldierExemption,
    SoldierExemptionFile,
    StorageDeleteOutbox,
)
from app.services.storage_uploads import commit_uploaded_objects, persist_uploaded_object
from app.storage.dependencies import get_object_storage
from app.storage.keys import make_object_key
from app.storage.protocol import StoredObject
from tests.helpers import auth_headers, create_soldier


def _parent_request(session):
    soldier = create_soldier(session, personal_number=f"upload{uuid.uuid4().hex[:8]}")
    exemption_type = ExemptionType(name=f"type{uuid.uuid4().hex[:8]}")
    session.add(exemption_type)
    session.flush()
    request = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=exemption_type.id, reason="test", status="pending_commander",
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return soldier, request


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def put_bytes(self, *, key, data, content_type, sha256):
        self.objects[key] = data
        return StoredObject(key, len(data), sha256, None, None)

    def open_read(self, *, key):
        import io

        return io.BytesIO(self.objects[key]), len(self.objects[key])

    def head(self, *, key):
        return None


def test_uploaded_object_commits_only_metadata(admin_session):
    admin, parent = _parent_request(admin_session)
    storage = FakeStorage()
    payload = b"%PDF test"
    row = ExemptionRequestFile(
        exemption_request_id=parent.id, file_name="x.pdf", content_type="application/pdf", uploaded_by=admin.id,
    )
    key = persist_uploaded_object(admin_session, storage, row, file_class="exemption_request", data=payload, content_type="application/pdf")
    admin_session.commit()

    assert key == make_object_key("exemption_request", row.id)
    assert row.data is None
    assert row.storage_key == key
    assert row.storage_sha256 == hashlib.sha256(payload).hexdigest()
    assert row.storage_size == len(payload)
    assert storage.objects == {key: payload}


def test_database_failure_enqueues_object_for_maintenance_cleanup(admin_session, monkeypatch):
    admin, parent = _parent_request(admin_session)
    storage = FakeStorage()
    row = ExemptionRequestFile(
        exemption_request_id=parent.id, file_name="x.pdf", content_type="application/pdf", uploaded_by=admin.id,
    )
    key = persist_uploaded_object(admin_session, storage, row, file_class="exemption_request", data=b"%PDF test", content_type="application/pdf")

    original_commit = admin_session.commit
    calls = 0

    def fail_once():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("db commit failed")
        original_commit()

    monkeypatch.setattr(admin_session, "commit", fail_once)
    with pytest.raises(Exception, match="upload_persistence_failed"):
        commit_uploaded_objects(admin_session, [key])

    assert not hasattr(storage, "delete")
    assert admin_session.query(StorageDeleteOutbox).filter_by(object_key=key).one()
    assert admin_session.get(ExemptionRequestFile, row.id) is None




def test_soldier_exemption_route_validates_before_object_write(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm{uuid.uuid4().hex[:8]}", role="admin")
    target = create_soldier(admin_session, personal_number=f"tgt{uuid.uuid4().hex[:8]}")
    exemption_type = ExemptionType(name=f"type{uuid.uuid4().hex[:8]}")
    admin_session.add(exemption_type)
    admin_session.flush()
    exemption = SoldierExemption(
        soldier_id=target.id, exemption_type_id=exemption_type.id, start_date=__import__("datetime").date.today(),
        granted_by=admin.id,
    )
    admin_session.add(exemption)
    admin_session.commit()
    storage = FakeStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        invalid = client.post(
            f"/api/soldiers/{target.id}/exemptions/{exemption.id}/files",
            files={"file": ("bad.png", b"%PDF wrong type", "image/png")}, headers=auth_headers(admin),
        )
        assert invalid.status_code == 400
        assert not storage.objects
        assert admin_session.query(SoldierExemptionFile).count() == 0

        valid = client.post(
            f"/api/soldiers/{target.id}/exemptions/{exemption.id}/files",
            files={"file": ("valid.pdf", b"%PDF valid bytes", "application/pdf")}, headers=auth_headers(admin),
        )
        assert valid.status_code == 201
        stored = admin_session.query(SoldierExemptionFile).one()
        assert stored.data is None
        assert stored.storage_key == f"soldier_exemption/{stored.id}"
        assert storage.objects[stored.storage_key] == b"%PDF valid bytes"
    finally:
        client.app.dependency_overrides.pop(get_object_storage, None)


def test_exemption_request_attachment_route_validates_before_object_write(client, admin_session):
    soldier, parent = _parent_request(admin_session)
    storage = FakeStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        invalid = client.post(
            f"/api/me/exemption-requests/{parent.id}/files",
            files={"file": ("bad.png", b"%PDF wrong type", "image/png")}, headers=auth_headers(soldier),
        )
        assert invalid.status_code == 400
        assert not storage.objects
        assert admin_session.query(ExemptionRequestFile).count() == 0

        valid = client.post(
            f"/api/me/exemption-requests/{parent.id}/files",
            files={"file": ("valid.pdf", b"%PDF valid bytes", "application/pdf")}, headers=auth_headers(soldier),
        )
        assert valid.status_code == 201
        stored = admin_session.query(ExemptionRequestFile).one()
        assert stored.data is None
        assert stored.storage_key == f"exemption_request/{stored.id}"
        assert storage.objects[stored.storage_key] == b"%PDF valid bytes"
    finally:
        client.app.dependency_overrides.pop(get_object_storage, None)
