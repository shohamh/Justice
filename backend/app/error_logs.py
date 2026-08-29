"""Read the structured application error logs for the admin console."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ErrorSource = Literal["backend", "frontend"]


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
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def read_error_logs(
    log_dir: Path,
    *,
    source: ErrorSource | None,
    offset: int,
    limit: int,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> PaginatedErrorLogs:
    files: list[tuple[ErrorSource, Path]] = []
    for name, file_source in (("backend-errors.log", "backend"), ("frontend-errors.log", "frontend")):
        if source is not None and source != file_source:
            continue
        files.extend((file_source, path) for path in log_dir.glob(f"{name}*"))

    entries: list[ErrorLogEntry] = []
    for file_source, path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            timestamp = record.get("ts") if isinstance(record.get("ts"), str) else None
            timestamp_key = _timestamp_key(timestamp)
            if from_ts and timestamp_key < from_ts:
                continue
            if to_ts and timestamp_key > to_ts:
                continue
            identity = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            entries.append(ErrorLogEntry(
                source=file_source,
                timestamp=timestamp,
                level=str(record.get("level", "ERROR")),
                message=str(record.get("msg", "")),
                request_id=record.get("request_id") if isinstance(record.get("request_id"), str) else None,
                details=record,
                record_key=identity,
            ))

    entries.sort(key=lambda entry: _timestamp_key(entry.timestamp), reverse=True)
    return PaginatedErrorLogs(items=entries[offset : offset + limit], total=len(entries))


def clear_error_logs_through(log_dir: Path, through: datetime) -> int:
    removed = 0
    with _pause_active_error_handlers(log_dir):
        for name in ("backend-errors.log", "frontend-errors.log"):
            for path in log_dir.glob(f"{name}*"):
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                except OSError:
                    continue
                kept: list[str] = []
                for line in lines:
                    try:
                        record = json.loads(line)
                        timestamp = _timestamp_key(record.get("ts"))
                    except (json.JSONDecodeError, TypeError):
                        kept.append(line)
                        continue
                    if timestamp <= through:
                        removed += 1
                    else:
                        kept.append(line)
                fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=log_dir)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                        temp_file.writelines(kept)
                    os.replace(temp_name, path)
                finally:
                    if os.path.exists(temp_name):
                        os.unlink(temp_name)
    return removed


@contextmanager
def _pause_active_error_handlers(log_dir: Path):
    active_paths = {
        (log_dir / name).resolve()
        for name in ("backend-errors.log", "frontend-errors.log")
    }
    paused: list[tuple[logging.Logger, logging.Handler]] = []
    for logger_name in ("backend.errors", "frontend.errors"):
        logger = logging.getLogger(logger_name)
        for handler in list(logger.handlers):
            base_filename = getattr(handler, "baseFilename", None)
            if base_filename is None or Path(base_filename).resolve() not in active_paths:
                continue
            # Serialize with any concurrent emit() before closing the stream.
            # Windows refuses os.replace() while another thread still owns the
            # file handle, even after the handler has been removed from logger.
            handler.acquire()
            try:
                logger.removeHandler(handler)
                handler.close()
                paused.append((logger, handler))
            except Exception:
                handler.release()
                raise
    try:
        yield
    finally:
        for logger, handler in paused:
            try:
                handler.stream = handler._open()  # type: ignore[attr-defined]
                logger.addHandler(handler)
            finally:
                handler.release()
