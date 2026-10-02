import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.file_authorization.policies import authorize_file
from app.file_authorization.schemas import ExemptionRequestFileRequest


def test_password_change_gate_blocks_protected_downloads():
    actor = SimpleNamespace(
        id=uuid.uuid4(), left_at=None, role="soldier", must_change_password=True
    )
    req = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=uuid.uuid4(), file_id=uuid.uuid4()
    )
    with pytest.raises(HTTPException) as exc:
        authorize_file(None, actor, req)
    assert exc.value.status_code == 403
