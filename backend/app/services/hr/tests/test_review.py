from __future__ import annotations

import uuid

import pytest

from app.db.models import SoldierHrProfile
from app.services.hr.review import ReviewActionError, clear_field_override, dismiss_held_for_review
from tests.helpers import create_soldier


def _held_profile(session, *, personal_number: str, reasons: list[str] = None) -> SoldierHrProfile:
    reasons = reasons or ["bad date"]
    profile = SoldierHrProfile(
        personal_number=personal_number, raw_dto={}, sync_status="held_for_review",
        review_reason="; ".join(reasons),
    )
    session.add(profile)
    session.commit()
    return profile


def test_dismiss_held_for_review_sets_dismissal_fields(admin_session):
    profile = _held_profile(admin_session, personal_number="rev-1", reasons=["bad date", "unmapped rank"])

    result = dismiss_held_for_review(admin_session, profile_id=profile.id)
    admin_session.commit()
    admin_session.refresh(profile)

    assert result.id == profile.id
    assert profile.review_dismissed_at is not None
    assert profile.review_dismissed_reasons == ["bad date", "unmapped rank"]


def test_dismiss_held_for_review_raises_on_unknown_profile(admin_session):
    with pytest.raises(ReviewActionError, match="profile_not_found"):
        dismiss_held_for_review(admin_session, profile_id=uuid.uuid4())


def test_dismiss_held_for_review_raises_when_not_held(admin_session):
    profile = SoldierHrProfile(personal_number="rev-2", raw_dto={}, sync_status="synced")
    admin_session.add(profile)
    admin_session.commit()

    with pytest.raises(ReviewActionError, match="not_held_for_review"):
        dismiss_held_for_review(admin_session, profile_id=profile.id)


def test_clear_field_override_removes_field_and_writes_audit(admin_session):
    soldier = create_soldier(admin_session, personal_number="rev-3")
    profile = SoldierHrProfile(
        personal_number="rev-3", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone", "email"],
    )
    admin_session.add(profile)
    admin_session.commit()

    result = clear_field_override(admin_session, profile_id=profile.id, field_name="phone", actor_id=None)
    admin_session.commit()
    admin_session.refresh(profile)

    assert result.overridden_fields == ["email"]
    assert profile.overridden_fields == ["email"]


def test_clear_field_override_raises_on_unknown_field_name(admin_session):
    soldier = create_soldier(admin_session, personal_number="rev-4")
    profile = SoldierHrProfile(
        personal_number="rev-4", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["phone"],
    )
    admin_session.add(profile)
    admin_session.commit()

    with pytest.raises(ReviewActionError, match="unknown_field"):
        clear_field_override(admin_session, profile_id=profile.id, field_name="not_a_real_field", actor_id=None)


def test_clear_field_override_raises_when_field_not_overridden(admin_session):
    soldier = create_soldier(admin_session, personal_number="rev-5")
    profile = SoldierHrProfile(
        personal_number="rev-5", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
        overridden_fields=["email"],
    )
    admin_session.add(profile)
    admin_session.commit()

    with pytest.raises(ReviewActionError, match="field_not_overridden"):
        clear_field_override(admin_session, profile_id=profile.id, field_name="phone", actor_id=None)
