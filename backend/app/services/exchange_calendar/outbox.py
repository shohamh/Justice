"""Transaction-scoped persistence helpers for Exchange calendar work."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from enum import IntEnum, StrEnum
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

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


def lease_lock_key(job_id: UUID) -> int:
    """Return a stable signed PostgreSQL advisory-lock key for a job."""
    return int.from_bytes(job_id.bytes[:8], byteorder="big", signed=True)


def enqueue_source(
    session: Session,
    source_type: str,
    source_id: UUID,
    *,
    priority: int,
    reason: str,
    event_date: date | None = None,
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
        event_date=event_date,
        reason=reason,
        status=ExchangeCalendarJobStatus.QUEUED.value,
    )
    session.execute(
        job_insert.on_conflict_do_update(
            index_elements=["source_type", "source_id"],
            index_where=ExchangeCalendarOutbox.status == ExchangeCalendarJobStatus.QUEUED.value,
            set_={
                "event_date": func.coalesce(job_insert.excluded.event_date, ExchangeCalendarOutbox.event_date),
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
    """Lease one due source while preserving caller-owned transaction boundaries."""
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
    leased_sibling = aliased(ExchangeCalendarOutbox)
    has_leased_sibling = (
        select(leased_sibling.id)
        .where(
            leased_sibling.source_type == ExchangeCalendarOutbox.source_type,
            leased_sibling.source_id == ExchangeCalendarOutbox.source_id,
            leased_sibling.status == ExchangeCalendarJobStatus.LEASED.value,
            leased_sibling.id != ExchangeCalendarOutbox.id,
        )
        .exists()
    )
    # The sync item row is a stable per-source mutex across distinct outbox jobs.
    candidate_statement = (
        select(ExchangeCalendarOutbox)
        .join(
            ExchangeCalendarSyncItem,
            and_(
                ExchangeCalendarSyncItem.source_type == ExchangeCalendarOutbox.source_type,
                ExchangeCalendarSyncItem.source_id == ExchangeCalendarOutbox.source_id,
            ),
        )
        .order_by(
            ExchangeCalendarOutbox.priority.desc(),
            ExchangeCalendarOutbox.event_date.asc().nullslast(),
            ExchangeCalendarOutbox.queued_at.asc(),
            ExchangeCalendarOutbox.id.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True, of=ExchangeCalendarSyncItem)
    )
    # A worker holds a session advisory lock for the full remote operation. The
    # transaction lock below fences the claim itself, while skipping candidates
    # that are still being processed even if their timestamp has expired.
    skipped: set[UUID] = set()
    while True:
        statement = candidate_statement.where(due_job, ~has_leased_sibling)
        if skipped:
            statement = statement.where(~ExchangeCalendarOutbox.id.in_(skipped))
        candidate = session.scalar(statement)
        if candidate is None:
            return None
        lock_acquired = session.scalar(
            select(func.pg_try_advisory_xact_lock(lease_lock_key(candidate.id)))
        )
        if lock_acquired:
            break
        skipped.add(candidate.id)

    # Recheck after locking the source row, then lease this exact job row.
    job_statement = (
        select(ExchangeCalendarOutbox)
        .where(
            ExchangeCalendarOutbox.id == candidate.id,
            due_job,
            ~has_leased_sibling,
        )
        .with_for_update(skip_locked=True)
    )
    job = session.scalar(job_statement)
    if job is None:
        return None

    job.status = ExchangeCalendarJobStatus.LEASED.value
    job.lease_owner = worker_id
    job.lease_expires_at = now_utc + LEASE_DURATION
    job.attempt_count += 1
    job.updated_at = now_utc
    return job


def renew_lease(
    session: Session,
    job_id: UUID,
    *,
    worker_id: str,
    attempt_count: int,
    now: datetime,
) -> bool:
    """Extend only the still-live generation owned by this worker."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now_utc = now.astimezone(UTC)
    result = session.execute(
        update(ExchangeCalendarOutbox)
        .where(
            ExchangeCalendarOutbox.id == job_id,
            ExchangeCalendarOutbox.status == ExchangeCalendarJobStatus.LEASED.value,
            ExchangeCalendarOutbox.lease_owner == worker_id,
            ExchangeCalendarOutbox.attempt_count == attempt_count,
            ExchangeCalendarOutbox.lease_expires_at > now_utc,
        )
        .values(lease_expires_at=now_utc + LEASE_DURATION, updated_at=now_utc)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
