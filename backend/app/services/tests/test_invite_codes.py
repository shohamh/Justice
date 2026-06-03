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


def test_create_invite_code_auto_generates_code(admin_session):
    from app.services.invite_codes import create_invite_code
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=3, actor_id=admin.id)
    admin_session.commit()
    assert len(code.code) == 8
    assert code.uses_left == 3


def test_consume_decrements_uses_left(admin_session):
    from app.services.invite_codes import create_invite_code, consume_invite_code
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=2, actor_id=admin.id)
    admin_session.commit()
    consume_invite_code(admin_session, code=code.code)
    admin_session.commit()
    admin_session.refresh(code)
    assert code.uses_left == 1


def test_consume_exhausted_raises(admin_session):
    import pytest
    from app.services.invite_codes import create_invite_code, consume_invite_code, InviteCodeError
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=1, actor_id=admin.id)
    admin_session.commit()
    consume_invite_code(admin_session, code=code.code)
    admin_session.commit()
    with pytest.raises(InviteCodeError, match="exhausted"):
        consume_invite_code(admin_session, code=code.code)


def test_consume_invalid_raises(admin_session):
    import pytest
    from app.services.invite_codes import consume_invite_code, InviteCodeError
    with pytest.raises(InviteCodeError, match="invalid"):
        consume_invite_code(admin_session, code="NOTEXIST")


def test_validate_code_true_for_valid(admin_session):
    from app.services.invite_codes import create_invite_code, validate_code
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=1, actor_id=admin.id)
    admin_session.commit()
    assert validate_code(admin_session, code=code.code) is True


def test_validate_code_false_for_exhausted(admin_session):
    from app.services.invite_codes import create_invite_code, consume_invite_code, validate_code
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    code = create_invite_code(admin_session, uses_left=1, actor_id=admin.id)
    admin_session.commit()
    consume_invite_code(admin_session, code=code.code)
    admin_session.commit()
    assert validate_code(admin_session, code=code.code) is False
