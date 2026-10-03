from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    DutyLocation,
    DutyShift,
    DutyType,
    ExchangeCalendarOutbox,
    ExchangeCalendarSyncAttempt,
    ExchangeCalendarSyncItem,
)
from app.services.exchange_calendar.outbox import (
    ExchangeCalendarJobPriority,
    ExchangeCalendarJobStatus,
    claim_next_job,
    enqueue_source,
)


def _source_id():
    return uuid4()


def _shift(session: Session) -> DutyShift:
    duty_type = DutyType(name=f"Exchange {uuid4()}", score_per_day=Decimal("1"))
    location = DutyLocation(name=f"Location {uuid4()}")
    session.add_all([duty_type, location])
    session.flush()
    shift = DutyShift(
        duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
        notes="original",
    )
    session.add(shift)
    session.flush()
    return shift


def test_sync_item_enforces_unique_source_key_and_status(admin_session: Session) -> None:
    key = _source_id()
    admin_session.add(ExchangeCalendarSyncItem(source_type="duty_shift", source_id=key, status="queued"))
    admin_session.flush()
    admin_session.add(ExchangeCalendarSyncItem(source_type="duty_shift", source_id=key, status="queued"))
    with pytest.raises(IntegrityError):
        admin_session.flush()
    admin_session.rollback()
    admin_session.add(ExchangeCalendarSyncItem(source_type="duty_shift", source_id=_source_id(), status="invalid"))
    with pytest.raises(IntegrityError):
        admin_session.flush()


def test_enqueue_coalesces_queued_but_keeps_follow_up_during_lease(admin_session: Session) -> None:
    # Earlier integration scenarios may commit outbox rows into this shared
    # test database. Keep this test's claim scoped to its own two jobs.
    admin_session.execute(delete(ExchangeCalendarOutbox))
    admin_session.expire_all()
    source_id = _source_id()
    now = datetime.now(UTC) + timedelta(days=1)
    enqueue_source(admin_session, "duty_shift", source_id, priority=ExchangeCalendarJobPriority.BACKFILL, reason="backfill")
    enqueue_source(admin_session, "duty_shift", source_id, priority=ExchangeCalendarJobPriority.USER_CHANGE, reason="user_change")
    jobs = admin_session.scalars(select(ExchangeCalendarOutbox).where(ExchangeCalendarOutbox.source_id == source_id)).all()
    assert len(jobs) == 1
    assert jobs[0].priority == ExchangeCalendarJobPriority.USER_CHANGE
    assert jobs[0].reason == "user_change"
    active = claim_next_job(admin_session, worker_id="worker-a", now=now)
    assert active is not None and active.status == ExchangeCalendarJobStatus.LEASED
    enqueue_source(admin_session, "duty_shift", source_id, priority=ExchangeCalendarJobPriority.URGENT, reason="user_change")
    queued = admin_session.scalars(select(ExchangeCalendarOutbox).where(ExchangeCalendarOutbox.source_id == source_id, ExchangeCalendarOutbox.status == "queued")).one()
    assert queued.id != active.id
    assert queued.priority == ExchangeCalendarJobPriority.URGENT
    active.status = ExchangeCalendarJobStatus.COMPLETED
    admin_session.flush()
    assert admin_session.get(ExchangeCalendarOutbox, queued.id).status == "queued"


def test_claim_priority_expiry_and_transaction_ownership(admin_session: Session) -> None:
    admin_session.execute(delete(ExchangeCalendarOutbox))
    admin_session.expire_all()
    now = datetime.now(UTC) + timedelta(days=1)
    low, high = _source_id(), _source_id()
    enqueue_source(admin_session, "duty_shift", low, priority=ExchangeCalendarJobPriority.BACKFILL, reason="backfill")
    enqueue_source(admin_session, "duty_shift", high, priority=ExchangeCalendarJobPriority.USER_CHANGE, reason="user_change")
    claimed = claim_next_job(admin_session, worker_id="first", now=now)
    assert claimed is not None and claimed.source_id == high and claimed.attempt_count == 1
    admin_session.commit()
    claimed.lease_expires_at = now - timedelta(seconds=1)
    admin_session.commit()
    recovered = claim_next_job(admin_session, worker_id="second", now=now + timedelta(seconds=1))
    assert recovered is not None and recovered.id == claimed.id and recovered.attempt_count == 2
    admin_session.rollback()
    stored = admin_session.get(ExchangeCalendarOutbox, claimed.id)
    assert stored.status == 'leased'
    assert stored.lease_owner == 'first'


def test_attempt_history_is_append_only(admin_session: Session) -> None:
    source_id = _source_id()
    enqueue_source(admin_session, "duty_shift", source_id, priority=10, reason="backfill")
    item = admin_session.scalar(select(ExchangeCalendarSyncItem).where(ExchangeCalendarSyncItem.source_id == source_id))
    admin_session.add_all([
        ExchangeCalendarSyncAttempt(sync_item_id=item.id, outcome="failed", error_category="timeout", error_message="request timed out"),
        ExchangeCalendarSyncAttempt(sync_item_id=item.id, outcome="created"),
    ])
    admin_session.flush()
    assert admin_session.scalar(select(func.count()).select_from(ExchangeCalendarSyncAttempt).where(ExchangeCalendarSyncAttempt.sync_item_id == item.id)) == 2


def test_source_update_and_enqueue_rollback_together(admin_session: Session) -> None:
    shift = _shift(admin_session)
    admin_session.commit()
    shift.notes = "changed"
    enqueue_source(admin_session, "duty_shift", shift.id, priority=100, reason="user_change")
    admin_session.flush()
    admin_session.rollback()
    persisted = admin_session.get(DutyShift, shift.id)
    assert persisted.notes == "original"
    assert admin_session.scalar(select(func.count()).select_from(ExchangeCalendarOutbox).where(ExchangeCalendarOutbox.source_id == shift.id)) == 0


def test_source_deletion_preserves_cancel_job_without_cascading_fk(admin_session: Session) -> None:
    shift = _shift(admin_session)
    admin_session.commit()
    source_id = shift.id
    enqueue_source(admin_session, "duty_shift", source_id, priority=ExchangeCalendarJobPriority.URGENT, reason="source_deleted")
    admin_session.delete(shift)
    admin_session.flush()
    job = admin_session.scalar(select(ExchangeCalendarOutbox).where(ExchangeCalendarOutbox.source_id == source_id))
    assert job is not None and job.reason == "source_deleted"
    assert not ExchangeCalendarOutbox.__table__.c.source_id.foreign_keys
