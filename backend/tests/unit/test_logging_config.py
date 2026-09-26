import json
import logging
import sys
from logging.handlers import RotatingFileHandler

import pytest

from app import logging_config

_ERROR_LOGGER_NAMES = ("backend.errors", "frontend.errors")


@pytest.fixture(autouse=True)
def _reset_loggers(monkeypatch):
    monkeypatch.delenv("LOKI_URL", raising=False)
    root = logging.getLogger()
    original_root_handlers = list(root.handlers)
    error_loggers = [logging.getLogger(name) for name in _ERROR_LOGGER_NAMES]
    original_error_state = [(lg, list(lg.handlers), lg.level, lg.propagate) for lg in error_loggers]
    # Start each test from error loggers with no handlers, as a fresh process would.
    for lg in error_loggers:
        lg.handlers = []
    original_excepthook = sys.excepthook
    yield
    for handler in list(root.handlers):
        if handler not in original_root_handlers:
            root.removeHandler(handler)
            handler.close()
    for lg, handlers, level, propagate in original_error_state:
        lg.handlers = handlers
        lg.setLevel(level)
        lg.propagate = propagate
    sys.excepthook = original_excepthook


def _all_handlers() -> list[logging.Handler]:
    handlers = list(logging.getLogger().handlers)
    for name in _ERROR_LOGGER_NAMES:
        handlers.extend(logging.getLogger(name).handlers)
    return handlers


def test_setup_logging_writes_no_log_files(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path / "logs")
    # pytest's own logging plugin keeps a FileHandler on root; only judge
    # what setup_logging() itself adds.
    before = set(_all_handlers())

    logging_config.setup_logging()
    logging.getLogger("app.test").info("hello from test")
    logging.getLogger("backend.errors").error("boom")

    added = [handler for handler in _all_handlers() if handler not in before]
    assert added
    assert not any(isinstance(handler, (logging.FileHandler, RotatingFileHandler)) for handler in added)
    assert not (tmp_path / "logs").exists()


def test_setup_logging_logs_to_stdout():
    logging_config.setup_logging()

    root_streams = [h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler]
    assert any(h.stream is sys.stdout for h in root_streams)


def test_error_loggers_still_reach_stdout_without_loki():
    logging_config.setup_logging()

    for name in _ERROR_LOGGER_NAMES:
        error_logger = logging.getLogger(name)
        assert error_logger.propagate is False
        assert error_logger.level == logging.ERROR
        assert any(type(h) is logging.StreamHandler and h.stream is sys.stdout for h in error_logger.handlers)
        assert not any(isinstance(h, logging_config._LokiHandler) for h in error_logger.handlers)


def test_error_loggers_push_json_to_a_dedicated_loki_stream(monkeypatch):
    monkeypatch.setenv("LOKI_URL", "http://loki.test:3100")
    monkeypatch.setenv("ENVIRONMENT", "test")

    logging_config.setup_logging()

    root_loki = [h for h in logging.getLogger().handlers if isinstance(h, logging_config._LokiHandler)]
    assert len(root_loki) == 1
    assert root_loki[0]._labels["env"] == "test"
    assert "log_type" not in root_loki[0]._labels

    for name in _ERROR_LOGGER_NAMES:
        error_loki = [h for h in logging.getLogger(name).handlers if isinstance(h, logging_config._LokiHandler)]
        assert len(error_loki) == 1
        assert error_loki[0] is not root_loki[0]
        assert error_loki[0]._labels["log_type"] == "errors"
        assert error_loki[0]._labels["env"] == "test"
        # The admin errors page parses these lines as JSON regardless of LOG_FORMAT.
        record = logging.LogRecord(name, logging.ERROR, __file__, 1, "boom", (), None)
        assert json.loads(error_loki[0].format(record))["logger"] == name


def test_loki_uses_development_environment_by_default(monkeypatch):
    monkeypatch.setenv("LOKI_URL", "http://loki.test:3100")
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    logging_config.setup_logging()

    root_loki = [h for h in logging.getLogger().handlers if isinstance(h, logging_config._LokiHandler)]
    assert root_loki[0]._labels["env"] == "development"


def test_setup_logging_is_idempotent_for_error_loggers(monkeypatch):
    monkeypatch.setenv("LOKI_URL", "http://loki.test:3100")

    logging_config.setup_logging()
    logging_config.setup_logging()

    for name in _ERROR_LOGGER_NAMES:
        handlers = logging.getLogger(name).handlers
        assert sum(isinstance(h, logging_config._LokiHandler) for h in handlers) == 1
        assert sum(type(h) is logging.StreamHandler for h in handlers) == 1


def test_setup_logging_reroutes_uvicorn_loggers_through_root():
    uv_logger = logging.getLogger("uvicorn.error")
    original_handlers = list(uv_logger.handlers)
    original_propagate = uv_logger.propagate
    uv_logger.addHandler(logging.NullHandler())
    uv_logger.propagate = False
    try:
        logging_config.setup_logging()
        assert uv_logger.propagate is True
        assert uv_logger.handlers == []
    finally:
        uv_logger.handlers = original_handlers
        uv_logger.propagate = original_propagate


def test_setup_logging_installs_excepthook():
    logging_config.setup_logging()

    assert sys.excepthook is logging_config._log_uncaught_exception


def test_setup_logging_warns_when_loki_is_not_configured(caplog):
    with caplog.at_level(logging.WARNING, logger="app.logging_config"):
        logging_config.setup_logging()

    warnings = [r for r in caplog.records if r.name == "app.logging_config" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "LOKI_URL" in warnings[0].getMessage()


def test_setup_logging_does_not_warn_when_loki_is_configured(monkeypatch, caplog):
    monkeypatch.setenv("LOKI_URL", "http://loki.test:3100")

    with caplog.at_level(logging.WARNING, logger="app.logging_config"):
        logging_config.setup_logging()

    assert not [r for r in caplog.records if r.name == "app.logging_config"]
