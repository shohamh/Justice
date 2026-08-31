"""Structured, privacy-aware logging for failed HTTP interactions."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import traceback
import uuid
from typing import Any

from fastapi import Request

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_SENSITIVE = re.compile(r"password|token|secret|authorization|cookie|refresh|access", re.I)
_MAX_VALUE = 4000
_MAX_BODY = 16000

# Caps how many times the *same* error can be logged in a burst — e.g. a hot
# loop hitting a broken endpoint, or a broken frontend retry loop — without
# flooding backend-errors.log/frontend-errors.log (and, downstream, the admin
# error inbox and its unread-count poll). Distinct errors are never affected:
# the limit is keyed per fingerprint, not global. Configurable via
# ERROR_LOG_RATE_LIMIT_MAX_PER_WINDOW / ERROR_LOG_RATE_LIMIT_WINDOW_SECONDS
# since the right threshold depends on the deployment's traffic.
_rate_limit_lock = threading.Lock()
_rate_limit_state: dict[str, tuple[float, int, int]] = {}  # fingerprint -> (window_start, count, suppressed)


def _check_rate_limit(fingerprint: str) -> tuple[bool, int]:
    """Returns (allow, suppressed_count_from_the_window_that_just_ended).

    allow=True means this occurrence should be logged normally. A non-zero
    suppressed count means the caller should first log one rollup line
    reporting that many occurrences of the same fingerprint were dropped
    during the window that just elapsed — so volume stays visible without
    flooding the log. A fingerprint that stops recurring entirely leaves its
    final tail of suppressed occurrences unreported (no background flush) —
    an accepted tradeoff for keeping this a plain in-memory counter."""
    from app.settings import get_settings

    settings = get_settings()
    max_per_window = settings.error_log_rate_limit_max_per_window
    window_seconds = settings.error_log_rate_limit_window_seconds

    now = time.monotonic()
    with _rate_limit_lock:
        window_start, count, suppressed = _rate_limit_state.get(fingerprint, (now, 0, 0))
        if now - window_start >= window_seconds:
            _rate_limit_state[fingerprint] = (now, 1, 0)
            return True, suppressed
        if count < max_per_window:
            _rate_limit_state[fingerprint] = (window_start, count + 1, suppressed)
            return True, 0
        _rate_limit_state[fingerprint] = (window_start, count, suppressed + 1)
        return False, 0


def request_id(value: str | None) -> str:
    return value if value and _REQUEST_ID_RE.fullmatch(value) else str(uuid.uuid4())


def redact(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if _SENSITIVE.search(str(key)) else redact(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value if len(value) <= _MAX_VALUE else value[:_MAX_VALUE] + "...[truncated]"
    return value


async def request_data(request: Request) -> dict[str, Any]:
    headers = {
        key: request.headers[key]
        for key in ("content-type", "user-agent", "referer")
        if key in request.headers
    }
    raw = await request.body()
    body: Any = None
    if raw:
        try:
            body = json.loads(raw[:_MAX_BODY])
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = raw[:_MAX_BODY].decode("utf-8", errors="replace")
    return {
        "method": request.method,
        "path": request.url.path,
        "query": redact(dict(request.query_params)),
        "headers": redact(headers),
        "body": redact(body),
    }


def _user_json(user: Any) -> dict[str, str] | None:
    if user is None or not getattr(user, "id", None):
        return None
    return {"id": str(user.id), "name": str(getattr(user, "full_name", user.id))}


def log_backend_exception(request: Request, exc: BaseException, data: dict[str, Any]) -> None:
    logger = logging.getLogger("backend.errors")
    request_id_value = getattr(request.state, "request_id", "unknown")
    user = _user_json(getattr(request.state, "user", None))
    ip = getattr(getattr(request, "client", None), "host", None)
    fingerprint = "backend:" + hashlib.sha256(
        f"{data.get('path', '')}|{type(exc).__name__}|{exc}".encode()
    ).hexdigest()
    allow, suppressed = _check_rate_limit(fingerprint)
    if suppressed:
        rollup_extra: dict[str, Any] = {
            "request_id": request_id_value,
            "suppressed_count": suppressed,
            "path": data.get("path"),
            "ip": ip,
        }
        if user is not None:
            rollup_extra["user"] = user
        logger.error(
            "Unhandled HTTP 500 (rate-limit rollup)",
            extra=rollup_extra,
        )
    if not allow:
        return
    extra: dict[str, Any] = {"request_id": request_id_value, "request": data, "traceback": "".join(traceback.format_exception(exc)), "ip": ip}
    if user is not None:
        extra["user"] = user
    logger.error(
        "Unhandled HTTP 500",
        extra=extra,
    )


def log_frontend_error(payload: dict[str, Any], *, user: Any = None, ip: str | None = None) -> None:
    logger = logging.getLogger("frontend.errors")
    request_id_value = payload.get("request_id", "unknown")
    fingerprint = "frontend:" + hashlib.sha256(
        f"{payload.get('kind', '')}|{payload.get('message', '')}|{payload.get('filename', '')}|{payload.get('line', '')}".encode()
    ).hexdigest()
    allow, suppressed = _check_rate_limit(fingerprint)
    if suppressed:
        rollup_extra = {"request_id": request_id_value, "suppressed_count": suppressed, "kind": payload.get("kind"), "ip": ip}
        user_json = _user_json(user)
        if user_json is not None:
            rollup_extra["user"] = user_json
        logger.error(
            "Frontend error (rate-limit rollup)",
            extra=rollup_extra,
        )
    if not allow:
        return
    user_json = _user_json(user)
    extra = {"request_id": request_id_value, "frontend": redact(payload), "ip": ip}
    if user_json is not None:
        extra["user"] = user_json
    logger.error(
        "Frontend error",
        extra=extra,
    )
