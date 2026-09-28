"""Transaction-scoped persistence helpers for Exchange calendar work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import ExchangeCalendarOutbox, ExchangeCalendarSyncItem


class ExchangeCalendarJobPriority(IntEnum):
    """Larger values are claimed before smaller values."""

    BACKFILL = 10
    RECONCILIATION = 50
    USER_CHANGE = 100
    URGENT = 200


class ExchangeCalendarJobStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExchangeCalendarSyncStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    SYNCED = "synced"
    PARTIAL = "partial"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    CANCELLED = "cancelled"


LEASE_DURATION = timedelta(minutes=5)
_SOURCE_TYPES = frozenset({"duty_shift", "duty_assignment", "range_event"})


def enqueue_source(
    session: Session,
    source_type: str,
    source_id: UUID,
    *,
    priority: int,
    reason: str,
) -> None:
    """Queue one source in the caller's transaction, coalescing queued work.

    The queued-only unique index means an edit during a lease becomes a distinct
    follow-up job, so completing the leased snapshot cannot erase that edit.
    """
    if source_type not in _SOURCE_TYPES:
        raise ValueError(f"unsupported Exchange calendar source type: {source_type}")
    if priority < 0:
        raise ValueError("priority must be non-negative")
    if not reason or len(reason) > 128:
        raise ValueError("reason must be a non-empty short category")

    sync_insert = insert(ExchangeCalendarSyncItem).values(
        source_type=source_type,
        source_id=source_id,
        status=ExchangeCalendarSyncStatus.QUEUED.value,
    )
    session.execute(
        sync_insert.on_conflict_do_update(
            index_elements=["source_type", "source_id"],
            set_={
                "status": case(
                    (
                        ExchangeCalendarSyncItem.status
                        == ExchangeCalendarSyncStatus.IN_PROGRESS.value,
                        ExchangeCalendarSyncStatus.IN_PROGRESS.value,
                    ),
                    else_=ExchangeCalendarSyncStatus.QUEUED.value,
                ),
                "updated_at": func.now(),
            },
        )
    )

    job_insert = insert(ExchangeCalendarOutbox).values(
        source_type=source_type,
        source_id=source_id,
        priority=int(priority),
        reason=reason,
        status=ExchangeCalendarJobStatus.QUEUED.value,
    )
    session.execute(
        job_insert.on_conflict_do_update(
            index_elements=["source_type", "source_id"],
            index_where=ExchangeCalendarOutbox.status
            == ExchangeCalendarJobStatus.QUEUED.value,
            set_={
                "priority": func.greatest(
                    ExchangeCalendarOutbox.priority,
                    job_insert.excluded.priority,
                ),
                "reason": case(
                    (
                        job_insert.excluded.priority >= ExchangeCalendarOutbox.priority,
                        job_insert.excluded.reason,
                    ),
                    else_=ExchangeCalendarOutbox.reason,
                ),
                "next_attempt_at": func.least(
                    ExchangeCalendarOutbox.next_attempt_at,
                    func.now(),
                ),
                "updated_at": func.now(),
            },
        )
    )


def claim_next_job(
    session: Session,
    *,
    worker_id: str,
    now: datetime,
) -> ExchangeCalendarOutbox | None:
    """Lease the next due job without committing the caller's transaction."""
    if not worker_id.strip():
        raise ValueError("worker_id must be non-empty")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now_utc = now.astimezone(UTC)

    due_job = or_(
        and_(
            ExchangeCalendarOutbox.status == ExchangeCalendarJobStatus.QUEUED.value,
            ExchangeCalendarOutbox.next_attempt_at <= now_utc,
        ),
        and_(
            ExchangeCalendarOutbox.status == ExchangeCalendarJobStatus.LEASED.value,
            ExchangeCalendarOutbox.lease_expires_at <= now_utc,
        ),
    )
    statement = (
        select(ExchangeCalendarOutbox)
        .where(due_job)
        .order_by(
            ExchangeCalendarOutbox.priority.desc(),
            ExchangeCalendarOutbox.queued_at.asc(),
            ExchangeCalendarOutbox.id.asc(),
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = session.scalar(statement)
    if job is None:
        return None

    job.status = ExchangeCalendarJobStatus.LEASED.value
    job.lease_owner = worker_id
    job.lease_expires_at = now_utc + LEASE_DURATION
    job.attempt_count += 1
    job.updated_at = now_utc
    return job
