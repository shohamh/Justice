import json
import logging
import time

import httpx
import respx

from app.logging_config import _LokiHandler


def _wait_until(condition, timeout_seconds: float = 2.0, poll_interval_seconds: float = 0.01) -> None:
    """Poll `condition` until it's true or `timeout_seconds` elapses.

    The push to Loki happens on _LokiHandler's background drain thread, so
    tests that assert on the resulting HTTP call must wait for it rather than
    checking immediately after the (now non-blocking) logger call returns.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(poll_interval_seconds)
    assert condition(), f"condition not met within {timeout_seconds}s"


@respx.mock
def test_loki_handler_pushes_formatted_record():
    route = respx.post("http://loki.test:3100/loki/api/v1/push").mock(
        return_value=httpx.Response(204)
    )
    handler = _LokiHandler(loki_url="http://loki.test:3100", app_label="justice-backend")
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("test.loki_handler")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    logger.error("boom")

    _wait_until(lambda: route.called)
    body = json.loads(route.calls.last.request.content)
    stream = body["streams"][0]
    assert stream["stream"] == {"app": "justice-backend", "level": "ERROR"}
    assert stream["values"][0][1] == "boom"


@respx.mock
def test_loki_handler_adds_extra_stream_labels():
    route = respx.post("http://loki.test:3100/loki/api/v1/push").mock(
        return_value=httpx.Response(204)
    )
    handler = _LokiHandler(
        loki_url="http://loki.test:3100", app_label="justice-backend", extra_labels={"log_type": "errors"}
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("test.loki_handler_labels")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    logger.error("boom")

    _wait_until(lambda: route.called)
    stream = json.loads(route.calls.last.request.content)["streams"][0]
    assert stream["stream"] == {"app": "justice-backend", "level": "ERROR", "log_type": "errors"}


@respx.mock
def test_loki_handler_never_raises_when_loki_is_unreachable():
    respx.post("http://loki.test:3100/loki/api/v1/push").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    handler = _LokiHandler(loki_url="http://loki.test:3100", app_label="justice-backend")
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("test.loki_handler_down")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    logger.error("this must not raise")  # would propagate via logging's own error handling if emit() raised


@respx.mock
def test_loki_handler_emit_does_not_block_on_slow_loki():
    """emit() must return almost immediately even if Loki hangs.

    _LokiHandler sits on the root logger and on backend.errors/frontend.errors,
    both called synchronously from request-handling code. If emit() performed
    the HTTP POST itself, a slow/unreachable Loki would stall the calling
    thread (up to the client's timeout) on every log call, which — on a
    single-threaded-per-worker ASGI server — cascades into concurrent request
    timeouts. The real push must happen on a background thread instead.
    """
    slow_response_delay_seconds = 3.0

    def slow_response(request: httpx.Request) -> httpx.Response:
        time.sleep(slow_response_delay_seconds)
        return httpx.Response(204)

    respx.post("http://loki.test:3100/loki/api/v1/push").mock(side_effect=slow_response)
    handler = _LokiHandler(loki_url="http://loki.test:3100", app_label="justice-backend")
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("test.loki_handler_slow")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

    started_at = time.monotonic()
    logger.error("must not block on the slow Loki response")
    elapsed_seconds = time.monotonic() - started_at

    assert elapsed_seconds < 1.0, (
        f"emit() blocked for {elapsed_seconds:.2f}s — the HTTP push must run "
        "on a background thread, not on the calling thread"
    )


@respx.mock
def test_loki_handler_on_root_logger_does_not_feed_back_on_itself():
    """Regression test for an infinite feedback loop when _LokiHandler sits
    on the ROOT logger (the real setup_logging() configuration once LOKI_URL
    is set).

    httpx (used internally by _drain_queue to POST to Loki) logs every
    outgoing request at INFO level on the "httpx" logger. That logger has no
    level of its own, so it inherits root's level, and its records propagate
    to root — where this same handler instance is attached. Without a guard,
    each push would log an httpx INFO line, which would get queued as another
    push, forever. This test attaches to root (unlike the other tests above,
    which use a throwaway child logger and would never observe this loop) and
    asserts Loki receives exactly one POST for one logged line.
    """
    route = respx.post("http://loki.test:3100/loki/api/v1/push").mock(
        return_value=httpx.Response(204)
    )
    handler = _LokiHandler(loki_url="http://loki.test:3100", app_label="justice-backend")
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    previous_level = root.level
    # Matches setup_logging(): root must be at INFO for httpx's INFO request
    # log to even be emitted, which is what makes this loop possible.
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        logging.getLogger("test.loki_handler_root").error("boom")
        time.sleep(1.0)  # let the drain thread (and any runaway re-entrancy) run
        assert route.call_count == 1, (
            f"expected exactly 1 POST to Loki, got {route.call_count} — "
            "the handler is feeding httpx's own request logging back into itself"
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
