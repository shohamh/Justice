import json
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler

from app.error_logs import clear_error_logs_through


def test_clear_error_logs_pauses_active_error_handlers(tmp_path, monkeypatch):
    log_path = tmp_path / "backend-errors.log"
    log_path.write_text(
        json.dumps({"ts": "2026-08-29T04:06:00+00:00", "msg": "old"}) + "\n"
        + json.dumps({"ts": "2026-08-29T04:20:00+00:00", "msg": "new"}) + "\n",
        encoding="utf-8",
    )
    logger = logging.getLogger("backend.errors")
    existing_handlers = list(logger.handlers)
    for existing_handler in existing_handlers:
        logger.removeHandler(existing_handler)
    handler = RotatingFileHandler(log_path, maxBytes=10_000_000, backupCount=5)
    logger.addHandler(handler)

    original_replace = os.replace

    def replace_rejecting_open_file(source, destination):
        if any(
            getattr(active, "stream", None) is not None
            and getattr(active, "baseFilename", None) == str(log_path)
            for active in logger.handlers
        ):
            raise PermissionError("active log file is locked")
        return original_replace(source, destination)

    monkeypatch.setattr("app.error_logs.os.replace", replace_rejecting_open_file)
    try:
        assert clear_error_logs_through(
            tmp_path,
            through=datetime.fromisoformat("2026-08-29T04:08:00+00:00"),
        ) == 1
        assert "old" not in log_path.read_text(encoding="utf-8")
        logger.error("after clear")
        assert "after clear" in log_path.read_text(encoding="utf-8")
    finally:
        logger.removeHandler(handler)
        handler.close()
        for existing_handler in existing_handlers:
            logger.addHandler(existing_handler)


def test_clear_error_logs_acquires_handler_lock_before_closing(tmp_path, monkeypatch):
    log_path = tmp_path / "backend-errors.log"
    log_path.write_text(
        json.dumps({"ts": "2026-08-29T04:06:00+00:00", "msg": "old"}) + "\n",
        encoding="utf-8",
    )
    logger = logging.getLogger("backend.errors")
    existing_handlers = list(logger.handlers)
    for existing_handler in existing_handlers:
        logger.removeHandler(existing_handler)
    handler = RotatingFileHandler(log_path, maxBytes=10_000_000, backupCount=5)
    logger.addHandler(handler)
    original_close = handler.close

    def close_requires_lock():
        assert handler.lock._is_owned()  # type: ignore[attr-defined]
        original_close()

    monkeypatch.setattr(handler, "close", close_requires_lock)
    try:
        assert clear_error_logs_through(
            tmp_path,
            through=datetime.fromisoformat("2026-08-29T04:08:00+00:00"),
        ) == 1
    finally:
        logger.removeHandler(handler)
        handler.close = original_close
        handler.close()
        for existing_handler in existing_handlers:
            logger.addHandler(existing_handler)
