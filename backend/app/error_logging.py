"""Structured, privacy-aware logging for failed HTTP interactions."""
from __future__ import annotations

import json
import logging
import re
import traceback
import uuid
from typing import Any

from fastapi import Request

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_SENSITIVE = re.compile(r"password|token|secret|authorization|cookie|refresh|access", re.I)
_MAX_VALUE = 4000
_MAX_BODY = 16000


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


def log_backend_exception(request: Request, exc: BaseException, data: dict[str, Any]) -> None:
    logging.getLogger("backend.errors").error(
        "Unhandled HTTP 500",
        extra={
            "request_id": getattr(request.state, "request_id", "unknown"),
            "request": data,
            "traceback": "".join(traceback.format_exception(exc)),
        },
    )


def log_frontend_error(payload: dict[str, Any]) -> None:
    logging.getLogger("frontend.errors").error(
        "Frontend error",
        extra={"request_id": payload.get("request_id", "unknown"), "frontend": redact(payload)},
    )
