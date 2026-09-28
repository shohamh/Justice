from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ExchangeCalendarOutbox
from app.services.exchange_calendar.outbox import (
    ExchangeCalendarJobPriority,
    claim_next_job,
    enqueue_source,
)


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
        assert verify_session.scalar(
            select(ExchangeCalendarOutbox.id).where(
                ExchangeCalendarOutbox.source_id.in_(source_ids),
                ExchangeCalendarOutbox.status == "queued",
            )
        ) is not None
