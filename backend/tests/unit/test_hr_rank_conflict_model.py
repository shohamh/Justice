from __future__ import annotations

import uuid

from app.db.models import HrRankConflict, Soldier, SoldierHrProfile
from tests.helpers import create_soldier


def test_hr_rank_conflict_round_trips(admin_session):
    soldier = create_soldier(admin_session, personal_number="hrc-1")
    conflict = HrRankConflict(
        soldier_id=soldier.id, old_rank="טוראי", new_rank="סמל",
        triggered_by_worker_decision=True, non_sequential_jump=False,
    )
    admin_session.add(conflict)
    admin_session.commit()
    admin_session.refresh(conflict)

    assert conflict.id is not None
    assert conflict.soldier_id == soldier.id
    assert conflict.old_rank == "טוראי"
    assert conflict.new_rank == "סמל"
    assert conflict.triggered_by_worker_decision is True
    assert conflict.non_sequential_jump is False
    assert conflict.hr_person_sync_id is None
    assert conflict.created_at is not None


def test_soldier_rank_last_set_by_defaults_to_none(admin_session):
    soldier = create_soldier(admin_session, personal_number="hrc-2")
    assert soldier.rank_last_set_by is None
    soldier.rank_last_set_by = "worker"
    admin_session.commit()
    admin_session.refresh(soldier)
    assert soldier.rank_last_set_by == "worker"


def test_soldier_hr_profile_dismissal_fields_default_to_none(admin_session):
    soldier = create_soldier(admin_session, personal_number="hrc-3")
    profile = SoldierHrProfile(personal_number="hrc-3", raw_dto={}, soldier_id=soldier.id)
    admin_session.add(profile)
    admin_session.commit()
    admin_session.refresh(profile)

    assert profile.review_dismissed_at is None
    assert profile.review_dismissed_reasons is None
