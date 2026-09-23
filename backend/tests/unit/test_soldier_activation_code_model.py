from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import SoldierActivationCode
from tests.helpers import create_soldier


def test_create_soldier_activation_code(admin_session):
    soldier = create_soldier(admin_session, personal_number="act-model-1")
    commander = create_soldier(admin_session, personal_number="act-model-cmd")

    code = SoldierActivationCode(
        soldier_id=soldier.id,
        code="AB12CD34",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=7),
        created_by=commander.id,
    )
    admin_session.add(code)
    admin_session.commit()
    admin_session.refresh(code)

    assert code.id is not None
    assert code.soldier_id == soldier.id
    assert code.code == "AB12CD34"
    assert code.used_at is None
    assert code.created_by == commander.id
    assert code.created_at is not None


def test_soldier_activation_code_code_is_unique(admin_session):
    from sqlalchemy.exc import IntegrityError
    import pytest

    s1 = create_soldier(admin_session, personal_number="act-model-2")
    s2 = create_soldier(admin_session, personal_number="act-model-3")
    now = datetime.now(tz=timezone.utc)

    admin_session.add(SoldierActivationCode(soldier_id=s1.id, code="DUPCODE1", expires_at=now + timedelta(days=1)))
    admin_session.commit()

    admin_session.add(SoldierActivationCode(soldier_id=s2.id, code="DUPCODE1", expires_at=now + timedelta(days=1)))
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()


def test_soldier_hr_onboarding_completed_at_defaults_none(admin_session):
    soldier = create_soldier(admin_session, personal_number="act-model-4")
    assert soldier.hr_onboarding_completed_at is None

    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    admin_session.commit()
    admin_session.refresh(soldier)
    assert soldier.hr_onboarding_completed_at is not None
