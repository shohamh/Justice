from __future__ import annotations

import uuid
from datetime import date

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyType, GimelimAttachment
from app.services.file_validation import validate_gimelim_file
from app.storage.dependencies import get_object_storage
from app.storage.protocol import StoredObject
from tests.helpers import auth_headers, create_soldier


def test_gimelim_webp_requires_complete_signature():
    assert validate_gimelim_file("image/webp", b"RIFF\x00\x00\x00\x00WEBPpayload") is None

    try:
        validate_gimelim_file("image/webp", b"RIFFxxxxNOPEpayload")
    except ValueError as exc:
        assert str(exc) == "invalid_file_type"
    else:
        raise AssertionError("RIFF without WEBP signature must be rejected")


class FakeObjectStorage:
    def __init__(self):
        self.objects = {}

    def put_bytes(self, *, key, data, content_type, sha256):
        self.objects[key] = data
        return StoredObject(key, len(data), sha256, None, None)

    def open_read(self, *, key):
        import io

        return io.BytesIO(self.objects[key]), len(self.objects[key])

    def head(self, *, key):
        return None


def test_gimelim_upload_rejects_signature_mismatch_before_storage(client, admin_session):
    soldier = create_soldier(admin_session, personal_number=f"gim{uuid.uuid4().hex[:8]}")
    duty_type = DutyType(name=f"type{uuid.uuid4().hex[:8]}", score_per_day=1)
    location = DutyLocation(name=f"loc{uuid.uuid4().hex[:8]}")
    admin_session.add_all([duty_type, location])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=duty_type.id, duty_location_id=location.id,
        start_date=date.today(), end_date=date.today(),
    )
    admin_session.add(assignment)
    admin_session.flush()
    dismissal = DutyDismissal(
        duty_assignment_id=assignment.id, dismissed_from=date.today(), dismissed_to=date.today(), is_gimelim=True,
    )
    admin_session.add(dismissal)
    admin_session.commit()
    storage = FakeObjectStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        invalid = client.post(
            f"/api/gimelim/{dismissal.id}/attachments",
            files={"file": ("bad.webp", b"RIFFxxxxNOPE", "image/webp")}, headers=auth_headers(soldier),
        )
        assert invalid.status_code == 400
        assert not storage.objects
        assert admin_session.query(GimelimAttachment).count() == 0

        valid_body = b"RIFF\x00\x00\x00\x00WEBPfake"
        valid = client.post(
            f"/api/gimelim/{dismissal.id}/attachments",
            files={"file": ("valid.webp", valid_body, "image/webp")}, headers=auth_headers(soldier),
        )
        assert valid.status_code == 201
        attachment = admin_session.query(GimelimAttachment).one()
        assert attachment.data is None
        assert attachment.storage_key == f"gimelim/{attachment.id}"
        assert storage.objects[attachment.storage_key] == valid_body
    finally:
        client.app.dependency_overrides.pop(get_object_storage, None)
