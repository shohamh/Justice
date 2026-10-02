"""Admin views of persisted Exchange calendar state; no Exchange I/O here."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import (
    DutyAssignment,
    DutyShift,
    ExchangeCalendarSyncAttempt,
    ExchangeCalendarSyncItem,
    ExchangeCalendarWorkerState,
    RangeEvent,
    Soldier,
)
from app.db.session import get_session
from app.services.exchange_calendar.outbox import ExchangeCalendarJobPriority, enqueue_source
from app.services.exchange_calendar.projection import AttendeeRole, ProjectionError, project_source

router = APIRouter(prefix="/admin/exchange-calendar-sync", tags=["exchange-calendar-sync"])
_ISRAEL = ZoneInfo("Asia/Jerusalem")
_STATES = ("queued", "in_progress", "synced", "partial", "retry_wait", "failed")
_RECENT_OUTCOMES = ("created", "updated", "cancelled", "partial", "failed")
_SAFE_ERRORS = {
    "missing_person": "An assigned person could not be found.",
    "missing_email": "An invited person has no usable email address.",
    "missing_source_label": "The schedule has a missing type or location.",
    "invalid_interval": "The schedule has an invalid date interval.",
    "invalid_local_time": "The schedule contains an invalid Israel local time.",
    "incomplete_range_time": "The range has only one of its two times.",
    "exchange_busy": "Exchange is busy. The worker will retry after backoff.",
    "exchange_unavailable": "Exchange is unavailable. The worker will retry.",
    "auth_failure": "Exchange authentication failed.",
    "item_failure": "Calendar item sync failed.",
}
_SAFE_CONNECTION_ERRORS = {
    "Exchange probe failed": ("exchange_unavailable", "Exchange probe failed."),
    "Exchange request failed": (
        "exchange_unavailable", "Exchange is unavailable. The worker will retry.",
    ),
    "Exchange is busy": (
        "exchange_busy", "Exchange is busy. The worker will retry after backoff.",
    ),
}


def _safe_category(category: str | None) -> str | None:
    return category if category in _SAFE_ERRORS else None


def _safe_error(category: str | None, raw: str | None) -> str | None:
    if category in _SAFE_ERRORS:
        return _SAFE_ERRORS[category]
    return "Calendar sync failed." if raw else None


def _safe_connection_error(raw: str | None) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    recognized = _SAFE_CONNECTION_ERRORS.get(raw)
    return recognized if recognized is not None else (None, "Calendar sync failed.")


class CountsOut(BaseModel):
    eligible: int
    queued: int
    in_progress: int
    synced: int
    partial: int
    retry_wait: int
    failed: int


class RecentOut(BaseModel):
    created: int
    updated: int
    cancelled: int
    partial: int
    failed: int


class SummaryOut(BaseModel):
    counts: CountsOut
    recent: RecentOut
    worker_heartbeat_at: datetime | None
    last_probe_at: datetime | None
    exchange_reachable: bool | None
    last_connection_attempt_at: datetime | None
    last_successful_contact_at: datetime | None
    latest_connection_error_category: str | None
    latest_connection_error: str | None
    global_backoff_until: datetime | None


class MissingAttendeeOut(BaseModel):
    name: str
    role: AttendeeRole


class ProblemOut(BaseModel):
    code: str
    message: str
    attendee: MissingAttendeeOut | None = None


class AttemptOut(BaseModel):
    outcome: str
    attempted_at: datetime
    error_category: str | None
    error: str | None


class EventOut(BaseModel):
    source_type: str
    source_id: UUID
    source_date: date | None
    event_label: str | None
    location: str | None
    status: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    error_category: str | None
    error: str | None
    current_projection_problems: list[ProblemOut]
    recent_attempts: list[AttemptOut]


class EventsOut(BaseModel):
    items: list[EventOut]
    total: int
    limit: int
    offset: int


class RetryOut(BaseModel):
    status: str


@router.get("/summary", response_model=SummaryOut)
def summary(
    session: Session = Depends(get_session),
    _user: Soldier = Depends(require_roles("admin")),
) -> SummaryOut:
    today = datetime.now(_ISRAEL).date()
    horizon = today.replace(year=today.year + 1) if not (today.month == 2 and today.day == 29) else today.replace(year=today.year + 1, day=28)
    grouped = dict(session.execute(
        select(ExchangeCalendarSyncItem.status, func.count())
        .group_by(ExchangeCalendarSyncItem.status)
    ).all())
    counts = {state: grouped.get(state, 0) for state in _STATES}
    # The outbox creates a sync row before its worker has filled source_date.
    # Count current eligible sources directly so queued work is visible immediately.
    counts["eligible"] = sum((
        session.scalar(select(func.count()).select_from(DutyShift).where(
            DutyShift.status == "active", DutyShift.end_date >= today,
            DutyShift.start_date <= horizon,
        )) or 0,
        session.scalar(select(func.count()).select_from(DutyAssignment).where(
            DutyAssignment.duty_shift_id.is_(None), DutyAssignment.status == "published",
            DutyAssignment.end_date >= today, DutyAssignment.start_date <= horizon,
        )) or 0,
        session.scalar(select(func.count()).select_from(RangeEvent).where(
            RangeEvent.status != "cancelled", RangeEvent.date.between(today, horizon),
        )) or 0,
    ))
    recent_since = datetime.now(UTC) - timedelta(hours=24)
    outcomes = dict(session.execute(
        select(ExchangeCalendarSyncAttempt.outcome, func.count())
        .where(ExchangeCalendarSyncAttempt.attempted_at >= recent_since)
        .group_by(ExchangeCalendarSyncAttempt.outcome)
    ).all())
    state = session.get(ExchangeCalendarWorkerState, 1)
    connection_error_category, connection_error = _safe_connection_error(
        state.latest_connection_error if state else None,
    )
    return SummaryOut(
        counts=CountsOut(**counts),
        recent=RecentOut(**{name: outcomes.get(name, 0) for name in _RECENT_OUTCOMES}),
        worker_heartbeat_at=state.heartbeat_at if state else None,
        last_probe_at=state.last_probe_at if state else None,
        exchange_reachable=state.exchange_reachable if state else None,
        last_connection_attempt_at=state.last_connection_attempt_at if state else None,
        last_successful_contact_at=state.last_successful_contact_at if state else None,
        latest_connection_error_category=connection_error_category,
        latest_connection_error=connection_error,
        global_backoff_until=state.global_backoff_until if state else None,
    )


@router.get("/events", response_model=EventsOut)
def events(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    _user: Soldier = Depends(require_roles("admin")),
) -> EventsOut:
    total = session.scalar(select(func.count()).select_from(ExchangeCalendarSyncItem)) or 0
    rows = session.scalars(
        select(ExchangeCalendarSyncItem)
        .order_by(ExchangeCalendarSyncItem.updated_at.desc(), ExchangeCalendarSyncItem.id.desc())
        .offset(offset).limit(limit)
    ).all()
    today = datetime.now(_ISRAEL).date()
    items: list[EventOut] = []
    for row in rows:
        problems: list[ProblemOut] = []
        source_date = row.source_date
        event_label: str | None = None
        location: str | None = None
        projection_day = today
        if row.exchange_item_id:
            model = {
                "duty_shift": DutyShift,
                "duty_assignment": DutyAssignment,
                "range_event": RangeEvent,
            }.get(row.source_type)
            source = session.get(model, row.source_id) if model else None
            if source is not None:
                # Tracked events keep following Justice after leaving the creation window.
                projection_day = source.date if row.source_type == "range_event" else source.start_date
        try:
            snapshot = project_source(session, row.source_type, row.source_id, today=projection_day)
            if snapshot:
                source_date = snapshot.start.date()
                event_label = snapshot.subject
                location = snapshot.location or None
                problems = [ProblemOut(
                    code=p.code,
                    message=p.safe_message,
                    attendee=MissingAttendeeOut(name=p.attendee.name, role=p.attendee.role)
                    if p.attendee else None,
                ) for p in snapshot.problems]
        except ProjectionError as exc:
            problems = [ProblemOut(code=exc.code, message=exc.safe_message)]
        attempts = session.scalars(
            select(ExchangeCalendarSyncAttempt)
            .where(ExchangeCalendarSyncAttempt.sync_item_id == row.id)
            .order_by(ExchangeCalendarSyncAttempt.attempted_at.desc(), ExchangeCalendarSyncAttempt.id.desc())
            .limit(5)
        ).all()
        items.append(EventOut(
            source_type=row.source_type, source_id=row.source_id, source_date=source_date,
            event_label=event_label, location=location,
            status=row.status, last_attempt_at=row.last_attempt_at, last_success_at=row.last_success_at,
            error_category=_safe_category(row.current_error_category),
            error=_safe_error(row.current_error_category, row.current_error),
            current_projection_problems=problems,
            recent_attempts=[AttemptOut(
                outcome=a.outcome, attempted_at=a.attempted_at,
                error_category=_safe_category(a.error_category),
                error=_safe_error(a.error_category, a.error_message),
            ) for a in attempts],
        ))
    return EventsOut(items=items, total=total, limit=limit, offset=offset)


@router.post("/events/{source_type}/{source_id}/retry", response_model=RetryOut, status_code=status.HTTP_202_ACCEPTED)
def retry(
    source_type: str,
    source_id: UUID,
    session: Session = Depends(get_session),
    _user: Soldier = Depends(require_roles("admin")),
) -> RetryOut:
    row = session.scalar(select(ExchangeCalendarSyncItem).where(
        ExchangeCalendarSyncItem.source_type == source_type,
        ExchangeCalendarSyncItem.source_id == source_id,
    ))
    if row is None:
        raise HTTPException(status_code=404, detail="calendar_source_not_found")
    if row.status not in {"failed", "partial", "retry_wait"}:
        raise HTTPException(status_code=409, detail="calendar_source_not_retryable")
    enqueue_source(session, source_type, source_id, priority=ExchangeCalendarJobPriority.URGENT, reason="admin_retry")
    session.commit()
    return RetryOut(status="accepted")
