import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.file_authorization.schemas import ExemptionRequestFileRequest
from app.file_gateway.routes import SlidingWindowRateLimiter, stream_authorized


class NeverAuth:
    async def authorize(self, *args):
        raise AssertionError("must not call authorization")


def _req(headers, limiter):
    app = SimpleNamespace(
        state=SimpleNamespace(
            authorization_client=NeverAuth(), download_semaphore=None, download_rate_limiter=limiter
        )
    )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "query_string": b"",
            "app": app,
        }
    )


def test_rate_limit_overflow_fails_before_authorization():
    limiter = SlidingWindowRateLimiter(limit=0)
    req = _req([(b"authorization", b"Bearer token")], limiter)
    file = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=uuid.uuid4(), file_id=uuid.uuid4()
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream_authorized(req, file))
    assert exc.value.status_code == 429


def test_cookie_alone_does_not_authenticate_gateway():
    req = _req([(b"cookie", b"access_token=token")], None)
    file = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=uuid.uuid4(), file_id=uuid.uuid4()
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream_authorized(req, file))
    assert exc.value.status_code == 401
