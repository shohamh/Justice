from __future__ import annotations

from app.db.models import HrPersonSync, HrPersonSyncError


def test_create_hr_person_sync_defaults(admin_session):
    run = HrPersonSync()
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.id is not None
    assert run.status == "running"
    assert run.started_at is not None
    assert run.completed_at is None
    assert run.total_fetched == 0
    assert run.created_count == 0
    assert run.updated_count == 0
    assert run.held_count == 0
    assert run.vanished_count == 0
    assert run.error_count == 0
    assert run.error_message is None


def test_hr_person_sync_completed_state_round_trips(admin_session):
    run = HrPersonSync(
        status="completed", total_fetched=10, created_count=3, updated_count=5,
        held_count=1, vanished_count=1, error_count=0,
    )
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.status == "completed"
    assert run.total_fetched == 10
    assert run.created_count == 3


def test_hr_person_sync_aborted_anomaly_state_round_trips(admin_session):
    run = HrPersonSync(status="aborted_anomaly", total_fetched=2, error_message="too few users")
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.status == "aborted_anomaly"
    assert run.error_message == "too few users"


def test_create_hr_person_sync_error(admin_session):
    run = HrPersonSync()
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    error = HrPersonSyncError(
        hr_person_sync_id=run.id, personal_number="1234567", error_message="boom",
    )
    admin_session.add(error)
    admin_session.commit()
    admin_session.refresh(error)

    assert error.id is not None
    assert error.hr_person_sync_id == run.id
    assert error.personal_number == "1234567"
    assert error.error_message == "boom"
    assert error.created_at is not None
