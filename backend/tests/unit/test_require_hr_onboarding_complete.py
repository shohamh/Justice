from __future__ import annotations

from fastapi import HTTPException
import pytest

from app.auth.deps import require_hr_onboarding_complete
from app.db.models import SoldierHrProfile
from tests.helpers import create_soldier


def test_blocks_hr_linked_soldier_with_incomplete_onboarding(admin_session):
    soldier = create_soldier(admin_session, personal_number="reqonb-1")
    admin_session.add(SoldierHrProfile(personal_number="reqonb-1", raw_dto={}, soldier_id=soldier.id))
    admin_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        require_hr_onboarding_complete(session=admin_session, user=soldier)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "hr_onboarding_incomplete"


def test_allows_hr_linked_soldier_with_completed_onboarding(admin_session):
    from datetime import datetime, timezone

    soldier = create_soldier(admin_session, personal_number="reqonb-2")
    admin_session.add(SoldierHrProfile(personal_number="reqonb-2", raw_dto={}, soldier_id=soldier.id))
    soldier.hr_onboarding_completed_at = datetime.now(tz=timezone.utc)
    admin_session.commit()

    result = require_hr_onboarding_complete(session=admin_session, user=soldier)
    assert result is soldier


def test_allows_soldier_with_no_hr_profile_regardless_of_flag(admin_session):
    soldier = create_soldier(admin_session, personal_number="reqonb-3")

    result = require_hr_onboarding_complete(session=admin_session, user=soldier)
    assert result is soldier
