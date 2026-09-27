from __future__ import annotations

from app.db.models import SoldierHrProfile
from tests.helpers import create_soldier


def test_create_soldier_hr_profile_without_soldier(admin_session):
    profile = SoldierHrProfile(
        personal_number="hrprof-001",
        raw_dto={"personalNumber": "hrprof-001", "fullName": "Held For Review"},
    )
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.id is not None
    assert profile.soldier_id is None
    assert profile.sync_status == "held_for_review"
    assert profile.review_reason is None
    assert profile.overridden_fields == []
    assert profile.last_synced_at is None
    assert profile.created_at is not None


def test_create_soldier_hr_profile_linked_to_soldier(admin_session):
    soldier = create_soldier(admin_session, personal_number="hrprof-002")

    profile = SoldierHrProfile(
        personal_number="hrprof-002",
        raw_dto={"personalNumber": "hrprof-002", "fullName": soldier.full_name},
        soldier_id=soldier.id,
        sync_status="synced",
    )
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.soldier_id == soldier.id
    assert profile.sync_status == "synced"


def test_soldier_hr_profile_personal_number_is_unique(admin_session):
    admin_session.add(SoldierHrProfile(personal_number="hrprof-003", raw_dto={}))
    admin_session.commit()

    admin_session.add(SoldierHrProfile(personal_number="hrprof-003", raw_dto={}))
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()


def test_soldier_hr_profile_overridden_fields_round_trips_list(admin_session):
    profile = SoldierHrProfile(
        personal_number="hrprof-004",
        raw_dto={},
        overridden_fields=["rank", "phone"],
    )
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.overridden_fields == ["rank", "phone"]
