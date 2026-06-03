from __future__ import annotations
import uuid
from tests.helpers import create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_registration_invite_code_model(admin_session):
    """RegistrationInviteCode can be inserted with uses_left."""
    from app.db.models import RegistrationInviteCode
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = RegistrationInviteCode(code=f"TESTCD{_uid()[:2].upper()}", uses_left=5, created_by=admin.id)
    admin_session.add(code)
    admin_session.commit()
    admin_session.refresh(code)
    assert code.id is not None
    assert code.uses_left == 5


def test_soldier_enrollment_request_model(admin_session):
    """SoldierEnrollmentRequest can be inserted with status=pending."""
    from app.db.models import SoldierEnrollmentRequest
    from tests.helpers import create_node
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(req)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.id is not None
    assert req.status == "pending"
