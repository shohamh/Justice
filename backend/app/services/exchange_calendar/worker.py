"""Independent Exchange calendar worker and durable outcome persistence."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from exchangelib.errors import (
    ErrorInternalServerTransientError,
    ErrorServerBusy,
    ErrorTimeoutExpired,
    UnauthorizedError,
)
from requests.exceptions import ConnectionError as RequestConnectionError
from requests.exceptions import Timeout as RequestTimeout
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    DutyAssignment,
    DutyShift,
    ExchangeCalendarOutbox,
    ExchangeCalendarSyncAttempt,
    ExchangeCalendarSyncItem,
    ExchangeCalendarWorkerState,
    RangeEvent,
)
from app.services.exchange_calendar.lease import LeaseLost, assert_lease_owned, maintain_lease
from app.services.exchange_calendar.outbox import (
    ExchangeCalendarJobStatus,
    ExchangeCalendarSyncStatus,
    claim_next_job,
    lease_lock_key,
    renew_lease,
)
from app.services.exchange_calendar.projection import ProjectionError, project_source
from app.services.exchange_calendar.rate_limiter import (
    ExchangeBackoffActive,
    ExchangeGateUnavailable,
)
from app.services.exchange_calendar.triggers import bootstrap_calendar_sources


@dataclass(frozen=True)
class WorkerOutcome:
    action: str
    item_id: str | None = None
    change_key: str | None = None
    content_hash: str | None = None
    source_date: date | None = None
    partial: bool = False
    error_category: str | None = None
    error_message: str | None = None
    retry_at: datetime | None = None
    global_backoff_until: datetime | None = None


class SqlCalendarRepository:
    def __init__(self, session_factory: sessionmaker[Session], worker_id: str):
        self.session_factory = session_factory
        self.worker_id = worker_id

    def _state(self, session: Session) -> ExchangeCalendarWorkerState:
        session.execute(
            insert(ExchangeCalendarWorkerState)
            .values(id=1)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        state = session.scalar(
            select(ExchangeCalendarWorkerState)
            .where(ExchangeCalendarWorkerState.id == 1).with_for_update()
        )
        if state is None:
            raise RuntimeError("Exchange calendar worker state is missing")
        return state

    def heartbeat(self, now: datetime) -> None:
        with self.session_factory.begin() as session:
            state = self._state(session)
            state.worker_id = self.worker_id
            state.heartbeat_at = now
            state.updated_at = now

    def probe_result(
        self, now: datetime, *, reachable: bool, error: str | None = None,
        backoff_until: datetime | None = None,
    ) -> None:
        with self.session_factory.begin() as session:
            state = self._state(session)
            state.last_probe_at = now
            if (
                reachable and state.exchange_reachable is False
                and state.last_connection_attempt_at is not None
                and now < state.last_connection_attempt_at
            ):
                # A success recorded out of order cannot erase a newer outage.
                return
            state.last_connection_attempt_at = now
            state.exchange_reachable = reachable
            state.latest_connection_error = error
            if backoff_until is not None:
                state.global_backoff_until = max(
                    state.global_backoff_until or backoff_until, backoff_until
                )
            if reachable:
                state.last_successful_contact_at = now
                if state.global_backoff_until and state.global_backoff_until <= now:
                    state.global_backoff_until = None
            state.updated_at = now

    def outage_state(self) -> tuple[bool, datetime | None]:
        with self.session_factory() as session:
            state = session.get(ExchangeCalendarWorkerState, 1)
            if state is None:
                return False, None
            return state.exchange_reachable is False, state.global_backoff_until

    def bootstrap(self, now: datetime) -> None:
        with self.session_factory.begin() as session:
            bootstrap_calendar_sources(session, now=now, batch_size=250)

    def claim(self, now: datetime) -> ExchangeCalendarOutbox | None:
        # The lease is committed before any EWS I/O.
        with self.session_factory.begin() as session:
            state = self._state(session)
            state.worker_id = self.worker_id
            state.heartbeat_at = now
            state.updated_at = now
            if state.exchange_reachable is False:
                return None
            if state.global_backoff_until and state.global_backoff_until > now:
                return None
            job = claim_next_job(session, worker_id=self.worker_id, now=now)
            if job is None:
                return None
            item = session.scalar(
                select(ExchangeCalendarSyncItem).where(
                    ExchangeCalendarSyncItem.source_type == job.source_type,
                    ExchangeCalendarSyncItem.source_id == job.source_id,
                )
            )
            if item is None:
                raise RuntimeError("Claimed Exchange job has no sync item")
            item.status = ExchangeCalendarSyncStatus.IN_PROGRESS.value
            session.flush()
            session.expunge(job)
            return job

    def renew(self, job: ExchangeCalendarOutbox, now: datetime) -> bool:
        with self.session_factory.begin() as session:
            return renew_lease(
                session,
                job.id,
                worker_id=self.worker_id,
                attempt_count=job.attempt_count,
                now=now,
            )

    @contextmanager
    def hold_lease_lock(self, job: ExchangeCalendarOutbox):
        """Keep an advisory lock across EWS I/O so expired work is not reclaimed."""
        engine = self.session_factory.kw.get("bind")
        if engine is None:
            raise RuntimeError("Exchange worker session factory has no bound engine")
        key = lease_lock_key(job.id)
        with engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
            connection.commit()
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                connection.commit()

    def current(self, job: ExchangeCalendarOutbox) -> ExchangeCalendarSyncItem:
        with self.session_factory() as session:
            item = session.scalar(
                select(ExchangeCalendarSyncItem).where(
                    ExchangeCalendarSyncItem.source_type == job.source_type,
                    ExchangeCalendarSyncItem.source_id == job.source_id,
                )
            )
            if item is None:
                raise RuntimeError("Exchange sync item is missing")
            session.expunge(item)
            return item

    def project(self, job: ExchangeCalendarOutbox, now: datetime):
        with self.session_factory() as session:
            today = now.astimezone(ZoneInfo("Asia/Jerusalem")).date()
            sync_item = session.scalar(
                select(ExchangeCalendarSyncItem).where(
                    ExchangeCalendarSyncItem.source_type == job.source_type,
                    ExchangeCalendarSyncItem.source_id == job.source_id,
                )
            )
            if sync_item is not None and sync_item.exchange_item_id:
                model = {
                    "duty_shift": DutyShift,
                    "duty_assignment": DutyAssignment,
                    "range_event": RangeEvent,
                }[job.source_type]
                source = session.get(model, job.source_id)
                if source is not None:
                    # Creation eligibility is a window around today. A meeting
                    # already mirrored to Exchange must follow its source for
                    # its full lifetime, including past and distant dates.
                    today = source.date if job.source_type == "range_event" else source.start_date
            return project_source(session, job.source_type, job.source_id, today=today)

    def complete(self, job: ExchangeCalendarOutbox, result: WorkerOutcome, now: datetime, **kwargs) -> bool:
        with self.session_factory.begin() as session:
            locked = session.scalar(
                select(ExchangeCalendarOutbox).where(ExchangeCalendarOutbox.id == job.id).with_for_update()
            )
            # A stale worker cannot overwrite the owner of a reclaimed job.
            if (
                locked is None or locked.status != ExchangeCalendarJobStatus.LEASED.value
                or locked.lease_owner != self.worker_id or locked.lease_expires_at is None
                or locked.lease_expires_at <= now
            ):
                return False
            item = session.scalar(
                select(ExchangeCalendarSyncItem).where(
                    ExchangeCalendarSyncItem.source_type == locked.source_type,
                    ExchangeCalendarSyncItem.source_id == locked.source_id,
                ).with_for_update()
            )
            if item is None:
                raise RuntimeError("Exchange sync item is missing")
            item.last_attempt_at = now
            item.updated_at = now
            item.current_error_category = result.error_category
            item.current_error = result.error_message
            if result.action == "failed":
                if result.retry_at:
                    item.status = ExchangeCalendarSyncStatus.RETRY_WAIT.value
                    queued_sibling = session.scalar(
                        select(ExchangeCalendarOutbox).where(
                            ExchangeCalendarOutbox.source_type == locked.source_type,
                            ExchangeCalendarOutbox.source_id == locked.source_id,
                            ExchangeCalendarOutbox.status == ExchangeCalendarJobStatus.QUEUED.value,
                            ExchangeCalendarOutbox.id != locked.id,
                        ).with_for_update()
                    )
                    if queued_sibling is None:
                        locked.status = ExchangeCalendarJobStatus.QUEUED.value
                        locked.next_attempt_at = result.retry_at
                    else:
                        # Preserve the newer user edit and its reason. The
                        # queued-only unique index permits exactly one row.
                        queued_sibling.priority = max(queued_sibling.priority, locked.priority)
                        queued_sibling.next_attempt_at = max(
                            queued_sibling.next_attempt_at, result.retry_at
                        )
                        locked.status = ExchangeCalendarJobStatus.COMPLETED.value
                else:
                    item.status = ExchangeCalendarSyncStatus.FAILED.value
                    locked.status = ExchangeCalendarJobStatus.FAILED.value
            else:
                item.exchange_item_id = result.item_id
                item.exchange_change_key = result.change_key
                item.content_hash = result.content_hash
                item.source_date = result.source_date
                item.last_success_at = now
                if result.action == "cancelled":
                    item.status = ExchangeCalendarSyncStatus.CANCELLED.value
                elif result.partial:
                    item.status = ExchangeCalendarSyncStatus.PARTIAL.value
                else:
                    item.status = ExchangeCalendarSyncStatus.SYNCED.value
                locked.status = ExchangeCalendarJobStatus.COMPLETED.value
            locked.lease_owner = None
            locked.lease_expires_at = None
            locked.updated_at = now
            session.add(ExchangeCalendarSyncAttempt(
                sync_item_id=item.id, job_id=locked.id,
                outcome="partial" if result.partial else result.action,
                error_category=result.error_category, error_message=result.error_message,
            ))
            state = self._state(session)
            if result.global_backoff_until:
                state.global_backoff_until = max(
                    state.global_backoff_until or result.global_backoff_until,
                    result.global_backoff_until,
                )
                state.exchange_reachable = False
                state.last_connection_attempt_at = now
                state.latest_connection_error = result.error_message
            elif result.action in ("created", "updated", "cancelled"):
                # Completion time is local DB time, not the time of EWS contact.
                # Only a successful probe can release a newer outage latch.
                if state.exchange_reachable is True:
                    state.last_successful_contact_at = now
            state.updated_at = now
            return True


class ExchangeCalendarWorker:
    PROBE_INTERVAL = timedelta(minutes=15)
    BOOTSTRAP_INTERVAL = timedelta(hours=6)

    def __init__(
        self, repository: object, client: object, *,
        bootstrap: Callable[[datetime], None] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        jitter: Callable[[], float] = random.random,
    ):
        self.repository = repository
        self.client = client
        self.bootstrap = bootstrap or repository.bootstrap
        self.clock = clock
        self.jitter = jitter
        self.last_probe: datetime | None = None
        self.last_probe_ok: bool | None = None
        self.next_probe_at: datetime | None = None
        self.last_bootstrap: datetime | None = None

    @staticmethod
    def _busy_seconds(exc: ErrorServerBusy) -> float:
        requested = exc.back_off
        if isinstance(requested, (int, float)) and math.isfinite(requested) and requested > 0:
            return max(60.0, float(requested))
        return 60.0

    def _probe(self, now: datetime) -> bool:
        shared_outage = False
        if hasattr(self.repository, "outage_state"):
            shared_outage, shared_deadline = self.repository.outage_state()
            if shared_outage and shared_deadline is not None and shared_deadline > now:
                return False
            if not shared_outage and self.last_probe_ok is False:
                # Another worker may have confirmed recovery.
                self.last_probe_ok = True
        if not shared_outage and self.next_probe_at is not None and now < self.next_probe_at:
            return self.last_probe_ok is True
        self.last_probe = now
        try:
            self.client.probe()
        except Exception as exc:
            response_at = self.clock()
            self.last_probe_ok = False
            if isinstance(exc, ExchangeBackoffActive):
                # The database already owns this deadline. Do not extend it
                # each time a local worker checks the gate.
                backoff_until = None
                self.next_probe_at = response_at + timedelta(seconds=60)
            else:
                seconds = self._busy_seconds(exc) if isinstance(exc, ErrorServerBusy) else 60
                backoff_until = response_at + timedelta(seconds=seconds)
                self.next_probe_at = backoff_until
            if hasattr(self.repository, "probe_result"):
                self.repository.probe_result(
                    response_at, reachable=False, error="Exchange probe failed",
                    backoff_until=backoff_until,
                )
            return False
        self.last_probe_ok = True
        self.next_probe_at = now + self.PROBE_INTERVAL
        if hasattr(self.repository, "probe_result"):
            self.repository.probe_result(now, reachable=True)
        return True

    def run_once(self, now: datetime) -> bool:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("worker clock must be timezone-aware")
        if hasattr(self.repository, "heartbeat"):
            self.repository.heartbeat(now)
        if not self._probe(now):
            return False
        bootstrap_now = self.clock()
        if (
            self.last_bootstrap is None
            or bootstrap_now - self.last_bootstrap >= self.BOOTSTRAP_INTERVAL
        ):
            self.bootstrap(bootstrap_now)
            self.last_bootstrap = self.clock()
        # Probes and source enumeration can take minutes. Lease from a fresh
        # clock sample after both, never from the start of the worker loop.
        job = self.repository.claim(self.clock())
        if job is None:
            return False
        try:
            renew = getattr(self.repository, "renew", None)
            renew_lease_now = (
                (lambda: renew(job, self.clock())) if renew is not None else (lambda: True)
            )
            hold_lock = getattr(self.repository, "hold_lease_lock", None)
            lock_context = hold_lock(job) if hold_lock is not None else nullcontext()
            with lock_context, maintain_lease(renew_lease_now):
                current = self.repository.current(job)
                snapshot = self.repository.project(job, self.clock())
                if snapshot is None:
                    # Find by stable source key even if CreateItem succeeded
                    # before Justice could persist the returned EWS item ID.
                    self.client.cancel(
                        f"{job.source_type}:{job.source_id}", current.exchange_item_id
                    )
                    result = WorkerOutcome("cancelled")
                elif (
                    current.exchange_item_id
                    and current.content_hash == snapshot.content_hash
                    and (
                        getattr(job, "reason", "")
                        not in {"backfill", "reconciliation", "reconcile"}
                        or self.client.matches(snapshot, current.exchange_item_id)
                    )
                ):
                    result = WorkerOutcome(
                        "unchanged", current.exchange_item_id, current.exchange_change_key,
                        snapshot.content_hash, snapshot.start.date(), bool(snapshot.problems),
                    )
                else:
                    ref = self.client.upsert(
                        snapshot, current.exchange_item_id, current.exchange_change_key,
                    )
                    result = WorkerOutcome(
                        ref.action, ref.item_id, ref.change_key, snapshot.content_hash,
                        snapshot.start.date(), bool(snapshot.problems),
                    )
                assert_lease_owned()
        except LeaseLost:
            # A newer worker owns this item. Do not persist an outcome or issue
            # another EWS request; the durable lease will be recovered later.
            return True
        except Exception as exc:
            result = self._failure(exc, job, self.clock())
        self.repository.complete(job, result, self.clock())
        return True

    def _failure(self, exc: Exception, job: ExchangeCalendarOutbox, now: datetime) -> WorkerOutcome:
        if isinstance(exc, ProjectionError):
            return WorkerOutcome("failed", error_category=exc.code, error_message=exc.safe_message)
        if isinstance(exc, ErrorServerBusy):
            until = now + timedelta(seconds=self._busy_seconds(exc))
            return WorkerOutcome(
                "failed", error_category="exchange_busy", error_message="Exchange is busy",
                retry_at=until, global_backoff_until=until,
            )
        if isinstance(exc, (
            RequestConnectionError, RequestTimeout, UnauthorizedError,
            ErrorTimeoutExpired, ErrorInternalServerTransientError,
            ExchangeBackoffActive, ExchangeGateUnavailable,
        )):
            delay = min(3600, 30 * 2 ** min(job.attempt_count, 7))
            return WorkerOutcome(
                "failed", error_category="exchange_unavailable",
                error_message="Exchange request failed",
                retry_at=now + timedelta(seconds=delay * (0.5 + self.jitter())),
                global_backoff_until=(
                    now + timedelta(seconds=60)
                    if isinstance(exc, (
                        RequestConnectionError, RequestTimeout, UnauthorizedError,
                        ErrorTimeoutExpired, ErrorInternalServerTransientError,
                    )) else None
                ),
            )
        return WorkerOutcome(
            "failed", error_category="item_failure", error_message="Calendar item sync failed",
        )
