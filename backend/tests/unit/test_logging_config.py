import logging
import sys

import pytest

from app import logging_config


@pytest.fixture(autouse=True)
def _reset_root_logger():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_excepthook = sys.excepthook
    yield
    for handler in list(root.handlers):
        if handler not in original_handlers:
            root.removeHandler(handler)
            handler.close()
    sys.excepthook = original_excepthook


def test_setup_logging_creates_log_dir_and_writes_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path / "logs")

    logging_config.setup_logging("backend.log")
    logging.getLogger("app.test").info("hello from test")

    log_file = tmp_path / "logs" / "backend.log"
    assert log_file.exists()
    assert "hello from test" in log_file.read_text(encoding="utf-8")


def test_setup_logging_reroutes_uvicorn_loggers_through_root(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path / "logs")
    uv_logger = logging.getLogger("uvicorn.error")
    original_handlers = list(uv_logger.handlers)
    original_propagate = uv_logger.propagate
    uv_logger.addHandler(logging.NullHandler())
    uv_logger.propagate = False
    try:
        logging_config.setup_logging("backend.log")
        assert uv_logger.propagate is True
        assert uv_logger.handlers == []
    finally:
        uv_logger.handlers = original_handlers
        uv_logger.propagate = original_propagate


def test_setup_logging_installs_excepthook(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path / "logs")

    logging_config.setup_logging("backend.log")

    assert sys.excepthook is logging_config._log_uncaught_exception
