import json
import logging

import httpx
import respx

from app.logging_config import _LokiHandler


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

    assert route.called
    body = json.loads(route.calls.last.request.content)
    stream = body["streams"][0]
    assert stream["stream"] == {"app": "justice-backend", "level": "ERROR"}
    assert stream["values"][0][1] == "boom"


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
