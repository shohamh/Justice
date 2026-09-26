"""Shared logging setup for the backend API and the Telegram bot process.

Logs go to stdout (the dev.ps1 / docker compose logs / container-runtime
view) and, when LOKI_URL is set, are also pushed straight to Loki. Nothing
is written to local log files: the process must stay stateless so it can
run as several replicas, and the admin errors page reads from Loki. Also
reroutes uvicorn's own loggers through the root logger and installs a
sys.excepthook so an uncaught exception in the main thread is logged before
the process dies.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx

# No longer used for logging itself (see the module docstring) — still the
# root for bug-report JSON mirrors (app/services/bug_reports.py). Native
# (dev.ps1) runs land here by default: backend/app/logging_config.py -> app/
# -> backend/ -> <project root>/logs. Docker overrides this via the LOG_DIR
# env var (set to /app/logs in docker-compose.yml) since the container's
# filesystem view starts at backend/, with nothing mounted above it.
_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR = Path(os.environ.get("LOG_DIR", str(_DEFAULT_LOG_DIR)))

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        standard = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
        fields = {
            key: value for key, value in record.__dict__.items()
            if key not in standard and not key.startswith("_")
        }
        return json.dumps({
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **fields,
            **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
        }, ensure_ascii=False)


class _LokiHandler(logging.Handler):
    """Pushes formatted log records straight to Loki's HTTP push API.

    Deliberately not a DaemonSet/Promtail setup — see the design doc. This
    means the app talks to Loki directly, so a Loki outage must never be
    allowed to crash or block request handling: every failure is swallowed
    AND the actual HTTP call never runs on the calling thread. Once LOKI_URL
    is set, this handler sits on the root logger (every INFO+ line) and on
    backend.errors/frontend.errors (called synchronously from the request
    path on every unhandled 500 — see app/error_logging.py). ASGI workers are
    single-threaded per event loop, so a slow/unreachable Loki must not be
    allowed to stall emit() for up to `timeout` seconds, which would cascade
    into concurrent request timeouts. emit() therefore only formats the
    record and enqueues it (non-blocking, dropping the line if the bounded
    queue is full); a single background daemon thread drains the queue and
    performs the actual POSTs sequentially.
    """

    def __init__(
        self,
        loki_url: str,
        app_label: str,
        timeout: float = 2.0,
        queue_maxsize: int = 1000,
        extra_labels: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._push_url = loki_url.rstrip("/") + "/loki/api/v1/push"
        self._labels = {
            "app": app_label,
            "env": os.environ.get("ENVIRONMENT", "development"),
            **(extra_labels or {}),
        }
        self._client = httpx.Client(timeout=timeout)
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._thread = threading.Thread(
            target=self._drain_queue, name="loki-handler", daemon=True
        )
        self._thread.start()

    def emit(self, record: logging.LogRecord) -> None:
        # Guard against a feedback loop: httpx (used by _drain_queue below to
        # perform the actual POST) logs every outgoing request at INFO level
        # on the "httpx" logger, which propagates to root — where this same
        # handler instance may be attached. Without this check, each push
        # would log an httpx line, which would queue another push, forever.
        if threading.current_thread() is self._thread:
            return
        try:
            line = self.format(record)
            ts_ns = str(int(record.created * 1_000_000_000))
            payload = {
                "streams": [
                    {
                        "stream": {**self._labels, "level": record.levelname},
                        "values": [[ts_ns, line]],
                    }
                ]
            }
            self._queue.put_nowait(payload)
        except Exception:
            # Covers queue.Full (queue saturated — drop the line rather than
            # block) and anything else (e.g. formatting errors).
            pass

    def _drain_queue(self) -> None:
        while True:
            payload = self._queue.get()
            try:
                self._client.post(self._push_url, json=payload)
            except Exception:
                pass


def _log_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    logging.getLogger("uncaught").critical(
        "UNCAUGHT EXCEPTION", exc_info=(exc_type, exc_value, exc_tb)
    )
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def setup_logging() -> None:
    use_json = os.environ.get("LOG_FORMAT", "").lower() == "json"
    formatter = _JsonFormatter() if use_json else logging.Formatter(_FORMAT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(stream_handler)

    # Defense in depth against log noise (and, combined with the drain-thread
    # guard in _LokiHandler.emit, a feedback loop): httpx logs every request
    # at INFO and httpcore (which it uses internally) logs at INFO/DEBUG.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    loki_url = os.environ.get("LOKI_URL", "").strip()
    app_label = os.environ.get("LOKI_APP_LABEL", "justice-backend")
    if loki_url:
        loki_handler = _LokiHandler(loki_url, app_label)
        loki_handler.setFormatter(formatter)
        root.addHandler(loki_handler)

    # The error loggers get their own Loki handler (created lazily, shared by
    # both): always JSON (the admin errors page parses every line, whatever
    # LOG_FORMAT says) and on a separate log_type="errors" stream, so
    # app/error_logs.py can select exactly these records instead of the
    # root INFO+ firehose.
    error_loki_handler: _LokiHandler | None = None
    for logger_name in ("backend.errors", "frontend.errors"):
        error_logger = logging.getLogger(logger_name)
        # propagate=False below keeps these records off the root handlers, so
        # give them their own stdout handler — otherwise, without Loki, they
        # would only reach logging's bare lastResort stderr fallback.
        if not any(getattr(h, "_justice_error_stdout", False) for h in error_logger.handlers):
            error_stream_handler = logging.StreamHandler(sys.stdout)
            error_stream_handler.setFormatter(formatter)
            error_stream_handler._justice_error_stdout = True  # type: ignore[attr-defined]
            error_logger.addHandler(error_stream_handler)
        if loki_url and not any(isinstance(h, _LokiHandler) for h in error_logger.handlers):
            if error_loki_handler is None:
                error_loki_handler = _LokiHandler(loki_url, app_label, extra_labels={"log_type": "errors"})
                error_loki_handler.setFormatter(_JsonFormatter())
            error_logger.addHandler(error_loki_handler)
        error_logger.setLevel(logging.ERROR)
        error_logger.propagate = False

    # uvicorn configures its own loggers with propagate=False and its own
    # StreamHandler before our module is imported. Clear those handlers and
    # let the records bubble to root instead, so uvicorn's request/error
    # logs go through the same handlers without printing twice to stdout.
    for name in _UVICORN_LOGGER_NAMES:
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True

    sys.excepthook = _log_uncaught_exception

    if not loki_url:
        logging.getLogger(__name__).warning(
            "LOKI_URL is not set: logs go to stdout only, and the admin errors "
            "page will report the error-log store as unavailable (HTTP 503)."
        )
