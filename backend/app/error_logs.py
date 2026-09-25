"""Query the application's error logs (in Loki) for the admin console, and
track each admin's own soft-clear cursor.

The error loggers ("backend.errors" / "frontend.errors") push JSON records
to Loki on their own stream, labeled log_type="errors" (see
app/logging_config.py), separate from the root logger's general INFO+
stream. This module only ever reads that dedicated stream.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from sqlalchemy.orm import Session

from app.db.models import AdminErrorClear

ErrorSource = Literal["backend", "frontend"]

# Stream selector for the error loggers' dedicated Loki stream. The bot
# process shares the same logging setup, so its error records are included.
ERROR_STREAM_SELECTOR = '{app=~"justice-backend|justice-bot", log_type="errors"}'

# Loki rejects query_range requests wider than `max_query_length` (721h by
# default) and limits above `max_entries_limit_per_query` (5000 by default)
# with a 400, so every query is clamped to stay inside both. Entries older
# than the window, or beyond the newest LOKI_MAX_ENTRIES in it, are not
# shown in the admin console (Grafana/Loki remain the place for deep dives).
LOKI_MAX_QUERY_RANGE = timedelta(days=30)
LOKI_MAX_ENTRIES = 5000


class LokiQueryError(RuntimeError):
    """Loki could not be queried (unreachable, timed out, or rejected the query)."""


@dataclass(frozen=True)
class ErrorLogEntry:
    source: ErrorSource
    timestamp: str | None
    level: str
    message: str
    request_id: str | None
    details: dict[str, Any]
    record_key: str


@dataclass(frozen=True)
class PaginatedErrorLogs:
    items: list[ErrorLogEntry]
    total: int


def _timestamp_key(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _to_ns(value: datetime) -> str:
    return str(int(value.timestamp() * 1_000_000_000))


def _query_loki(loki_url: str, *, query: str, from_ts: datetime, to_ts: datetime, limit: int) -> list[dict[str, Any]]:
    try:
        response = httpx.get(
            f"{loki_url.rstrip('/')}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": _to_ns(from_ts),
                "end": _to_ns(to_ts),
                "limit": limit,
                "direction": "BACKWARD",
            },
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LokiQueryError(f"Loki query failed: {exc}") from exc

    records: list[dict[str, Any]] = []
    for stream in data.get("data", {}).get("result", []):
        for _ts_ns, line in stream.get("values", []):
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def read_error_logs(
    loki_url: str,
    *,
    source: ErrorSource | None,
    offset: int,
    limit: int,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> PaginatedErrorLogs:
    """Return one page of error log entries, newest first.

    An empty `loki_url` (Loki not configured for this deployment) yields an
    empty result rather than an error. Raises LokiQueryError if Loki is
    configured but the query fails.
    """
    if not loki_url:
        return PaginatedErrorLogs(items=[], total=0)

    effective_to = to_ts or datetime.now(UTC)
    earliest_allowed = effective_to - LOKI_MAX_QUERY_RANGE
    effective_from = from_ts if from_ts is not None and from_ts > earliest_allowed else earliest_allowed
    if effective_from > effective_to:
        # e.g. a `to` filter earlier than the admin's soft-clear cursor —
        # nothing can match, and Loki would reject the inverted range.
        return PaginatedErrorLogs(items=[], total=0)

    raw = _query_loki(loki_url, query=ERROR_STREAM_SELECTOR, from_ts=effective_from, to_ts=effective_to, limit=LOKI_MAX_ENTRIES)

    entries: list[ErrorLogEntry] = []
    for record in raw:
        # Backend and frontend errors share one stream (both are logged by
        # the backend process); the record's own "logger" field tells them apart.
        record_source: ErrorSource = "frontend" if record.get("logger") == "frontend.errors" else "backend"
        if source is not None and source != record_source:
            continue
        timestamp = record.get("ts") if isinstance(record.get("ts"), str) else None
        timestamp_key = _timestamp_key(timestamp)
        if from_ts and timestamp_key < from_ts:
            continue
        if to_ts and timestamp_key > to_ts:
            continue
        identity = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        entries.append(ErrorLogEntry(
            source=record_source,
            timestamp=timestamp,
            level=str(record.get("level", "ERROR")),
            message=str(record.get("msg", "")),
            request_id=record.get("request_id") if isinstance(record.get("request_id"), str) else None,
            details=record,
            record_key=identity,
        ))

    entries.sort(key=lambda entry: _timestamp_key(entry.timestamp), reverse=True)
    return PaginatedErrorLogs(items=entries[offset : offset + limit], total=len(entries))


def cleared_before(session: Session, *, admin_id: uuid.UUID) -> datetime | None:
    """This admin's soft-clear cursor: entries at or before it are hidden."""
    row = session.get(AdminErrorClear, admin_id)
    return row.cleared_before if row is not None else None


def mark_cleared_through(session: Session, *, admin_id: uuid.UUID, through: datetime) -> None:
    """Hide this admin's entries at or before `through`. The cursor only ever
    moves forward, so an older `through` than the current one is a no-op.
    The caller commits."""
    row = session.get(AdminErrorClear, admin_id)
    if row is None:
        session.add(AdminErrorClear(admin_id=admin_id, cleared_before=through))
    elif through > row.cleared_before:
        row.cleared_before = through
