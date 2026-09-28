from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateIndex

from app.db.models import ExchangeCalendarOutbox, ExchangeCalendarSyncItem
from app.services.exchange_calendar.outbox import (
    ExchangeCalendarJobPriority,
    ExchangeCalendarJobStatus,
    claim_next_job,
    enqueue_source,
)


def _clear_exchange_calendar_queue(engine) -> None:
    with Session(engine) as session:
        session.execute(delete(ExchangeCalendarOutbox))
        session.execute(delete(ExchangeCalendarSyncItem))
        session.commit()


@pytest.fixture(autouse=True)
def isolate_exchange_calendar_queue(admin_engine):
    _clear_exchange_calendar_queue(admin_engine)
    yield
    _clear_exchange_calendar_queue(admin_engine)


def test_parallel_workers_skip_a_locked_job(admin_engine) -> None:
    source_ids = [uuid4(), uuid4()]
    with Session(admin_engine) as setup:
        for index, source_id in enumerate(source_ids):
            enqueue_source(
                setup,
                "duty_shift",
                source_id,
                priority=ExchangeCalendarJobPriority.USER_CHANGE - index,
                reason="user_change",
            )
        setup.commit()

    session_factory = sessionmaker(bind=admin_engine, expire_on_commit=False)
    first_session = session_factory()
    second_session = session_factory()
    try:
        now = datetime.now(UTC) + timedelta(days=1)
        first_claim = claim_next_job(first_session, worker_id="worker-a", now=now)
        assert first_claim is not None
        second_claim = claim_next_job(second_session, worker_id="worker-b", now=now)
        assert second_claim is not None
        assert second_claim.id != first_claim.id
        assert second_claim.source_id != first_claim.source_id
    finally:
        first_session.rollback()
        second_session.rollback()
        first_session.close()
        second_session.close()

    with Session(admin_engine) as verify_session:
        assert (
            verify_session.scalar(
                select(ExchangeCalendarOutbox.id).where(
                    ExchangeCalendarOutbox.source_id.in_(source_ids),
                    ExchangeCalendarOutbox.status == "queued",
                )
            )
            is not None
        )


def test_same_source_follow_up_waits_for_active_lease_resolution(admin_engine) -> None:
    source_id = uuid4()
    now = datetime.now(UTC) + timedelta(days=1)
    session_factory = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with session_factory() as setup_session:
        enqueue_source(
            setup_session,
            "duty_shift",
            source_id,
            priority=ExchangeCalendarJobPriority.USER_CHANGE,
            reason="user_change",
        )
        setup_session.commit()

    first_session = session_factory()
    second_session = session_factory()
    try:
        active_job = claim_next_job(first_session, worker_id="worker-a", now=now)
        assert active_job is not None
        first_session.commit()

        enqueue_source(
            second_session,
            "duty_shift",
            source_id,
            priority=ExchangeCalendarJobPriority.BACKFILL,
            reason="backfill",
        )
        second_session.commit()

        active_job.lease_expires_at = now - timedelta(seconds=1)
        first_session.commit()

        reclaimed_job = claim_next_job(first_session, worker_id="worker-a", now=now)
        assert reclaimed_job is not None
        assert reclaimed_job.id == active_job.id

        uncommitted_race_claim = claim_next_job(second_session, worker_id="worker-b", now=now)
        assert uncommitted_race_claim is None

        first_session.commit()
        committed_active_claim = claim_next_job(second_session, worker_id="worker-b", now=now)
        assert committed_active_claim is None

        active_job.status = ExchangeCalendarJobStatus.COMPLETED
        first_session.commit()

        follow_up_job = claim_next_job(second_session, worker_id="worker-b", now=now)
        assert follow_up_job is not None
        assert follow_up_job.id != active_job.id
        assert follow_up_job.source_id == source_id
    finally:
        first_session.rollback()
        second_session.rollback()
        first_session.close()
        second_session.close()


def test_expired_job_is_reclaimed_before_higher_priority_follow_up(admin_engine) -> None:
    source_id = uuid4()
    now = datetime.now(UTC) + timedelta(days=1)
    session_factory = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with session_factory() as setup_session:
        enqueue_source(
            setup_session,
            "duty_shift",
            source_id,
            priority=ExchangeCalendarJobPriority.BACKFILL,
            reason="backfill",
        )
        setup_session.commit()

    first_session = session_factory()
    second_session = session_factory()
    try:
        original_job = claim_next_job(first_session, worker_id="worker-a", now=now)
        assert original_job is not None
        first_session.commit()

        enqueue_source(
            second_session,
            "duty_shift",
            source_id,
            priority=ExchangeCalendarJobPriority.URGENT,
            reason="user_change",
        )
        second_session.commit()

        original_job.lease_expires_at = now - timedelta(seconds=1)
        first_session.commit()

        reclaimed_job = claim_next_job(first_session, worker_id="worker-a", now=now)
        assert reclaimed_job is not None
        assert reclaimed_job.id == original_job.id
        first_session.commit()

        assert claim_next_job(second_session, worker_id="worker-b", now=now) is None
    finally:
        first_session.rollback()
        second_session.rollback()
        first_session.close()
        second_session.close()


def test_due_index_orders_priority_desc_in_model_and_database(admin_engine) -> None:
    model_index = next(
        index
        for index in ExchangeCalendarOutbox.__table__.indexes
        if index.name == "ix_exchange_calendar_outbox_due"
    )
    model_definition = str(CreateIndex(model_index).compile(dialect=postgresql.dialect()))
    assert "priority DESC" in model_definition

    with admin_engine.connect() as connection:
        database_definition = connection.scalar(
            text("SELECT pg_get_indexdef('ix_exchange_calendar_outbox_due'::regclass)")
        )
    assert database_definition is not None
    assert "priority DESC" in database_definition
