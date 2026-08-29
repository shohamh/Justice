from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.models import AdminErrorRead, Soldier
from app.db.session import get_session
from app.error_logs import clear_error_logs_through, read_error_logs
from app.logging_config import LOG_DIR

router = APIRouter(tags=["admin_errors"])


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
    result = read_error_logs(LOG_DIR, source=source, offset=offset, limit=limit, from_ts=from_, to_ts=to)
    read_keys = set(session.scalars(select(AdminErrorRead.record_key).where(AdminErrorRead.admin_id == admin.id)).all())
    return PaginatedErrorLogsOut(
        items=[ErrorLogEntryOut.model_validate({**entry.__dict__, "unread": entry.record_key not in read_keys}) for entry in result.items],
        total=result.total,
    )


@router.get("/admin/errors/unread-count")
def admin_error_unread_count(session: Session = Depends(get_session), admin: Soldier = Depends(require_roles("admin"))) -> dict[str, int]:
    entries = read_error_logs(LOG_DIR, source=None, offset=0, limit=100000).items
    read_keys = set(session.scalars(select(AdminErrorRead.record_key).where(AdminErrorRead.admin_id == admin.id)).all())
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
    entries = read_error_logs(LOG_DIR, source=source, offset=0, limit=100000, from_ts=from_, to_ts=to).items
    existing = set(session.scalars(select(AdminErrorRead.record_key).where(AdminErrorRead.admin_id == admin.id)).all())
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
def clear_admin_errors(through: datetime = Query(...), _admin: Soldier = Depends(require_roles("admin"))) -> dict[str, int]:
    return {"removed": clear_error_logs_through(LOG_DIR, through.astimezone(UTC))}
