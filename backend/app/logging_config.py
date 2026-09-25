"""Shared logging setup for the backend API and the Telegram bot process.

Attaches a rotating file handler (so crashes leave a trail on disk) and a
stdout handler (so the existing dev.ps1 / docker compose logs terminal view
keeps working) to the root logger, reroutes uvicorn's own loggers through
it, and installs a sys.excepthook so an uncaught exception in the main
thread is logged before the process dies.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx

# Native (dev.ps1) runs land here by default: backend/app/logging_config.py
# -> app/ -> backend/ -> <project root>/logs. Docker overrides this via the
# LOG_DIR env var (set to /app/logs in docker-compose.yml) since the
# container's filesystem view starts at backend/, with nothing mounted above
# it.
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
    allowed to crash or block request handling: every failure is swallowed.
    """

    def __init__(self, loki_url: str, app_label: str, timeout: float = 2.0) -> None:
        super().__init__()
        self._push_url = loki_url.rstrip("/") + "/loki/api/v1/push"
        self._app_label = app_label
        self._client = httpx.Client(timeout=timeout)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            ts_ns = str(int(record.created * 1_000_000_000))
            payload = {
                "streams": [
                    {
                        "stream": {"app": self._app_label, "level": record.levelname},
                        "values": [[ts_ns, line]],
                    }
                ]
            }
            self._client.post(self._push_url, json=payload)
        except Exception:
            pass


def _log_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    logging.getLogger("uncaught").critical(
        "UNCAUGHT EXCEPTION", exc_info=(exc_type, exc_value, exc_tb)
    )
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def setup_logging(log_filename: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    use_json = os.environ.get("LOG_FORMAT", "").lower() == "json"
    formatter = _JsonFormatter() if use_json else logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_DIR / log_filename, maxBytes=10_000_000, backupCount=5
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    loki_url = os.environ.get("LOKI_URL", "").strip()
    if loki_url:
        app_label = os.environ.get("LOKI_APP_LABEL", "justice-backend")
        loki_handler = _LokiHandler(loki_url, app_label)
        loki_handler.setFormatter(formatter)
        root.addHandler(loki_handler)
    else:
        loki_handler = None

    for logger_name, filename in (("backend.errors", "backend-errors.log"), ("frontend.errors", "frontend-errors.log")):
        error_logger = logging.getLogger(logger_name)
        if not any(getattr(handler, "_justice_error_log", False) for handler in error_logger.handlers):
            error_handler = RotatingFileHandler(LOG_DIR / filename, maxBytes=10_000_000, backupCount=5)
            error_handler.setFormatter(_JsonFormatter())
            error_handler._justice_error_log = True  # type: ignore[attr-defined]
            error_logger.addHandler(error_handler)
        if loki_handler is not None and not any(isinstance(h, _LokiHandler) for h in error_logger.handlers):
            error_logger.addHandler(loki_handler)
        error_logger.setLevel(logging.ERROR)
        error_logger.propagate = False

    # uvicorn configures its own loggers with propagate=False and its own
    # StreamHandler before our module is imported. Clear those handlers and
    # let the records bubble to root instead, so uvicorn's request/error
    # logs land in the same file without printing twice to stdout.
    for name in _UVICORN_LOGGER_NAMES:
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True

    sys.excepthook = _log_uncaught_exception
