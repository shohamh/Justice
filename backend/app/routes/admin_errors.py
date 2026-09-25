import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import AdminErrorRead, Soldier
from app.db.session import get_session
from app.error_logs import LokiQueryError, PaginatedErrorLogs, cleared_before, mark_cleared_through, read_error_logs
from app.settings import get_settings

router = APIRouter(tags=["admin_errors"])

# A plain module logger (propagates to root), deliberately not
# backend.errors/frontend.errors: a Loki outage must not feed the very
# error-log stream this module reads from.
logger = logging.getLogger(__name__)

_LOKI_UNAVAILABLE = "Error log store (Loki) is unavailable"

# Reading "everything" (unread count, mark-all-read) is bounded by
# error_logs.LOKI_MAX_ENTRIES anyway; this just asks for all of it.
_ALL = 100000


class ErrorLogEntryOut(BaseModel):
    source: Literal["backend", "frontend"]
    timestamp: str | None
    level: str
    message: str
    request_id: str | None
    details: dict[str, object]
    record_key: str
    unread: bool


class PaginatedErrorLogsOut(BaseModel):
    items: list[ErrorLogEntryOut]
    total: int


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _apply_soft_clear(session: Session, admin: Soldier, from_: datetime | None, to: datetime | None) -> tuple[datetime | None, datetime | None]:
    """Narrow [from_, to] so nothing at or before this admin's soft-clear
    cursor is returned. read_error_logs' `from_ts` is inclusive, so the
    cursor is bumped by the smallest timestamp step (1µs, the precision of
    the records' ISO-8601 `ts`) to exclude an entry exactly at the cutoff."""
    from_, to = _as_utc(from_), _as_utc(to)
    cutoff = cleared_before(session, admin_id=admin.id)
    if cutoff is None:
        return from_, to
    first_visible = cutoff + timedelta(microseconds=1)
    if from_ is None or from_ < first_visible:
        from_ = first_visible
    return from_, to


def _read(**kwargs) -> PaginatedErrorLogs:
    loki_url = get_settings().loki_url
    if not loki_url:
        # Unconfigured must not look like "no errors" in the admin UI.
        raise HTTPException(status_code=503, detail=f"{_LOKI_UNAVAILABLE}: LOKI_URL is not configured")
    try:
        return read_error_logs(loki_url, **kwargs)
    except LokiQueryError as exc:
        logger.warning("Admin errors: Loki query failed", exc_info=exc)
        raise HTTPException(status_code=503, detail=_LOKI_UNAVAILABLE) from exc


def _read_keys(session: Session, admin: Soldier) -> set[str]:
    return set(session.scalars(select(AdminErrorRead.record_key).where(AdminErrorRead.admin_id == admin.id)).all())


@router.get("/admin/errors", response_model=PaginatedErrorLogsOut)
def list_admin_errors(
    source: Literal["backend", "frontend"] | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
    admin: Soldier = Depends(require_roles("admin")),
) -> PaginatedErrorLogsOut:
    from_, to = _apply_soft_clear(session, admin, from_, to)
    result = _read(source=source, offset=offset, limit=limit, from_ts=from_, to_ts=to)
    read_keys = _read_keys(session, admin)
    return PaginatedErrorLogsOut(
        items=[ErrorLogEntryOut.model_validate({**entry.__dict__, "unread": entry.record_key not in read_keys}) for entry in result.items],
        total=result.total,
    )


@router.get("/admin/errors/unread-count")
def admin_error_unread_count(session: Session = Depends(get_session), admin: Soldier = Depends(require_roles("admin"))) -> dict[str, int]:
    from_, _ = _apply_soft_clear(session, admin, None, None)
    entries = _read(source=None, offset=0, limit=_ALL, from_ts=from_).items
    read_keys = _read_keys(session, admin)
    return {"count": sum(entry.record_key not in read_keys for entry in entries)}


class MarkErrorsReadBody(BaseModel):
    entries: list[dict[str, str]]


@router.post("/admin/errors/mark-all-read", status_code=204, response_model=None)
def mark_all_admin_errors_read(
    source: Literal["backend", "frontend"] | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    session: Session = Depends(get_session),
    admin: Soldier = Depends(require_roles("admin")),
) -> None:
    from_, to = _apply_soft_clear(session, admin, from_, to)
    entries = _read(source=source, offset=0, limit=_ALL, from_ts=from_, to_ts=to).items
    existing = _read_keys(session, admin)
    for entry in entries:
        if entry.record_key not in existing:
            session.add(AdminErrorRead(admin_id=admin.id, source=entry.source, record_key=entry.record_key))
    session.commit()


@router.post("/admin/errors/mark-read", status_code=204, response_model=None)
def mark_admin_errors_read(body: MarkErrorsReadBody, session: Session = Depends(get_session), admin: Soldier = Depends(require_roles("admin"))) -> None:
    for entry in body.entries[:1000]:
        key, source = entry.get("record_key"), entry.get("source")
        if not key or source not in {"backend", "frontend"}:
            continue
        exists = session.scalar(select(AdminErrorRead.id).where(AdminErrorRead.admin_id == admin.id, AdminErrorRead.source == source, AdminErrorRead.record_key == key))
        if exists is None:
            session.add(AdminErrorRead(admin_id=admin.id, source=source, record_key=key))
    session.commit()


@router.delete("/admin/errors")
def clear_admin_errors(through: datetime = Query(...), session: Session = Depends(get_session), admin: Soldier = Depends(require_roles("admin"))) -> dict[str, str]:
    """Soft clear: hide this admin's error entries at or before `through`.
    Log data in Loki is never deleted, and other admins are unaffected.
    `through` is capped at now so a future date can't hide errors that
    haven't happened yet."""
    through_utc = min(_as_utc(through), datetime.now(UTC))
    mark_cleared_through(session, admin_id=admin.id, through=through_utc)
    session.commit()
    return {"status": "cleared"}
