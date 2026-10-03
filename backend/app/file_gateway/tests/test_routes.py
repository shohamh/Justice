import asyncio
import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.file_authorization.schemas import ExemptionRequestFileRequest, FileAuthorizationDecision
from app.file_gateway.response_headers import build_file_headers
from app.file_gateway.routes import stream_authorized


def test_headers_are_private_sanitized_and_inline_only_for_raster():
    headers = build_file_headers(
        filename='..\\bad\r\n"file.png', content_type="image/png", size=5, inline=True
    )
    assert headers["Cache-Control"] == "private, no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Disposition"].startswith("inline;")
    assert "\r" not in headers["Content-Disposition"] and "\n" not in headers["Content-Disposition"]
    assert build_file_headers(
        filename="active.svg", content_type="image/svg+xml", size=1, inline=True
    )["Content-Disposition"].startswith("attachment;")


def _request(client, *, headers=None, semaphore=None):
    app = SimpleNamespace(
        state=SimpleNamespace(authorization_client=client, download_semaphore=semaphore)
    )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers or [(b"authorization", b"Bearer token")],
            "query_string": b"",
            "app": app,
        }
    )


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    async def authorize(self, request, token, *, request_id=None):
        if self.error:
            raise self.error
        return self.result


class FakeStorage:
    def __init__(self, data=b"hello"):
        self.data = io.BytesIO(data)
        self.opened = []

    def open_read(self, *, key):
        self.opened.append(key)
        return self.data, len(self.data.getvalue())


def test_denial_and_noncanonical_key_never_open_storage(monkeypatch):
    import app.file_gateway.routes as routes

    file_id = uuid.uuid4()
    storage = FakeStorage()
    monkeypatch.setattr(routes, "get_object_storage", lambda: storage)
    req = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=uuid.uuid4(), file_id=file_id
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream_authorized(_request(FakeClient(error=PermissionError())), req))
    assert exc.value.status_code == 404 and storage.opened == []
    forged = FileAuthorizationDecision(
        object_key=f"exemption_request/{uuid.uuid4()}",
        sha256="a" * 64,
        size=5,
        content_type="text/plain",
        filename="a.txt",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream_authorized(_request(FakeClient(result=forged)), req))
    assert exc.value.status_code == 503 and storage.opened == []


def test_stream_holds_capacity_through_body_consumption(monkeypatch):
    import app.file_gateway.routes as routes

    file_id = uuid.uuid4()
    decision = FileAuthorizationDecision(
        object_key=f"exemption_request/{file_id}",
        sha256="a" * 64,
        size=5,
        content_type="text/plain",
        filename="a.txt",
    )
    storage = FakeStorage()
    monkeypatch.setattr(routes, "get_object_storage", lambda: storage)
    semaphore = asyncio.Semaphore(1)
    req = _request(FakeClient(result=decision), semaphore=semaphore)

    async def run():
        response = await stream_authorized(
            req,
            ExemptionRequestFileRequest(
                kind="exemption_request", request_id=uuid.uuid4(), file_id=file_id
            ),
        )
        assert semaphore._value == 0
        chunks = [chunk async for chunk in response.body_iterator]
        await response.background()
        assert semaphore._value == 1 and b"".join(chunks) == b"hello"

    asyncio.run(run())


def test_range_rejected_before_authorization():

    req = _request(
        FakeClient(error=AssertionError("must not authorize")),
        headers=[(b"authorization", b"Bearer token"), (b"range", b"bytes=0-1")],
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            stream_authorized(
                req,
                ExemptionRequestFileRequest(
                    kind="exemption_request", request_id=uuid.uuid4(), file_id=uuid.uuid4()
                ),
            )
        )
    assert exc.value.status_code == 416
