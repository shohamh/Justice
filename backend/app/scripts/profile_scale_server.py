"""Serve Justice locally with request-scoped SQL and ASGI wall timing headers.

Run with ``python -m app.scripts.profile_scale_server --port 18000`` from
``backend``. The wrapper binds only to loopback and does not modify the normal
application or expose SQL text, parameters, or database configuration.
"""

from __future__ import annotations

import argparse
import contextvars
import threading
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy import event

from app.db.session import _engine
from app.main import app as justice_app

_request_stats: contextvars.ContextVar[QueryStats | None] = contextvars.ContextVar(
    "scale_profile_query_stats", default=None
)
_query_starts = threading.local()


@dataclass
class QueryStats:
    """Mutable accumulator shared by async request work and its DB worker thread."""

    count: int = 0
    elapsed_seconds: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


def _before_cursor_execute(
    _connection: Any,
    _cursor: Any,
    _statement: str,
    _parameters: Any,
    _context: Any,
    _executemany: bool,
) -> None:
    stats = _request_stats.get()
    if stats is None:
        return

    starts = getattr(_query_starts, "stack", None)
    if starts is None:
        starts = []
        _query_starts.stack = starts
    starts.append(perf_counter())
    with stats.lock:
        stats.count += 1


def _after_cursor_execute(
    _connection: Any,
    _cursor: Any,
    _statement: str,
    _parameters: Any,
    _context: Any,
    _executemany: bool,
) -> None:
    stats = _request_stats.get()
    starts = getattr(_query_starts, "stack", None)
    if stats is None or not starts:
        return

    elapsed = perf_counter() - starts.pop()
    with stats.lock:
        stats.elapsed_seconds += elapsed


def _handle_cursor_error(_exception_context: Any) -> None:
    stats = _request_stats.get()
    starts = getattr(_query_starts, "stack", None)
    if stats is None or not starts:
        return

    elapsed = perf_counter() - starts.pop()
    with stats.lock:
        stats.elapsed_seconds += elapsed


def _install_sql_timers() -> None:
    event.listen(_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(_engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(_engine, "handle_error", _handle_cursor_error)


class ScaleProfileMiddleware:
    """Add local-only SQL totals to each ASGI response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_started = perf_counter()
        stats = QueryStats()
        token = _request_stats.set(stats)

        async def send_with_metrics(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                with stats.lock:
                    count = stats.count
                    elapsed_ms = stats.elapsed_seconds * 1000
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-scale-db-queries", str(count).encode("ascii")),
                        (b"x-scale-db-ms", f"{elapsed_ms:.3f}".encode("ascii")),
                        (
                            b"x-scale-server-ms",
                            f"{(perf_counter() - request_started) * 1000:.3f}".encode("ascii"),
                        ),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_metrics)
        finally:
            _request_stats.reset(token)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    import uvicorn

    _install_sql_timers()
    uvicorn.run(
        ScaleProfileMiddleware(justice_app),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
