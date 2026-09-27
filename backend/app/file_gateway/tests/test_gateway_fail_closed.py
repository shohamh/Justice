import asyncio
import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.file_authorization.schemas import ExemptionRequestFileRequest, FileAuthorizationDecision
from app.file_gateway.routes import stream_authorized
from app.storage.keys import make_object_key


class Client:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    async def authorize(self, *args):
        if self.error:
            raise self.error
        return self.result


class Body:
    def __init__(self, data):
        self.inner = io.BytesIO(data)
        self.closed = False

    def read(self, size=-1):
        return self.inner.read(size)

    def close(self):
        self.closed = True
        self.inner.close()


class Store:
    def __init__(self, data, reported_size=None, error=None):
        self.body = Body(data)
        self.reported_size = reported_size
        self.error = error
        self.opened = []

    def open_read(self, *, key):
        self.opened.append(key)
        if self.error:
            raise self.error
        return self.body, self.reported_size if self.reported_size is not None else len(
            self.body.inner.getvalue()
        )


def req(client, *, semaphore=None):
    app = SimpleNamespace(
        state=SimpleNamespace(authorization_client=client, download_semaphore=semaphore)
    )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"authorization", b"Bearer token")],
            "query_string": b"",
            "app": app,
        }
    )


def decision(file_id, size=5):
    return FileAuthorizationDecision(
        object_key=make_object_key("exemption_request", file_id),
        sha256="a" * 64,
        size=size,
        content_type="text/plain",
        filename="a.txt",
    )


def test_authorization_timeout_and_outage_fail_closed_without_storage(monkeypatch):
    import app.file_gateway.routes as routes

    store = Store(b"hello")
    monkeypatch.setattr(routes, "get_object_storage", lambda: store)
    request = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=uuid.uuid4(), file_id=uuid.uuid4()
    )
    for error in (TimeoutError(), RuntimeError("authorization unavailable")):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(stream_authorized(req(Client(error=error)), request))
        assert exc.value.status_code == 503
    assert store.opened == []


def test_oversized_and_invalid_metadata_fail_before_storage(monkeypatch):
    import app.file_gateway.routes as routes

    store = Store(b"hello")
    monkeypatch.setattr(routes, "get_object_storage", lambda: store)
    file_id = uuid.uuid4()
    request = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=uuid.uuid4(), file_id=file_id
    )
    oversized = decision(file_id, 26 * 1024 * 1024)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream_authorized(req(Client(oversized)), request))
    assert exc.value.status_code == 503 and store.opened == []
    malformed = SimpleNamespace(
        object_key=make_object_key("exemption_request", file_id),
        size=5,
        content_type="text/plain\r\nX-Evil: yes",
        filename="a.txt",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream_authorized(req(Client(malformed)), request))
    assert exc.value.status_code == 503 and store.opened == []


def test_storage_outage_is_503_and_no_bytes_are_returned(monkeypatch):
    import app.file_gateway.routes as routes

    file_id = uuid.uuid4()
    monkeypatch.setattr(routes, "get_object_storage", lambda: Store(b"", error=OSError("down")))
    request = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=uuid.uuid4(), file_id=file_id
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream_authorized(req(Client(decision(file_id))), request))
    assert exc.value.status_code == 503


def test_body_size_mismatch_closes_stream_and_releases_capacity(monkeypatch):
    import app.file_gateway.routes as routes

    file_id = uuid.uuid4()
    store = Store(b"oversized", reported_size=5)
    monkeypatch.setattr(routes, "get_object_storage", lambda: store)
    semaphore = asyncio.Semaphore(1)
    request = req(Client(decision(file_id)), semaphore=semaphore)

    async def run():
        response = await stream_authorized(
            request,
            ExemptionRequestFileRequest(
                kind="exemption_request", request_id=uuid.uuid4(), file_id=file_id
            ),
        )
        with pytest.raises(RuntimeError):
            async for _ in response.body_iterator:
                pass
        await response.background()
        assert store.body.closed and semaphore._value == 1

    asyncio.run(run())


def test_client_disconnect_closes_object_body_and_releases_capacity(monkeypatch):
    import app.file_gateway.routes as routes

    file_id = uuid.uuid4()
    store = Store(b"hello")
    monkeypatch.setattr(routes, "get_object_storage", lambda: store)
    semaphore = asyncio.Semaphore(1)
    request = req(Client(decision(file_id)), semaphore=semaphore)

    async def run():
        response = await stream_authorized(
            request,
            ExemptionRequestFileRequest(
                kind="exemption_request", request_id=uuid.uuid4(), file_id=file_id
            ),
        )
        iterator = response.body_iterator
        assert await iterator.__anext__() == b"hello"
        await iterator.aclose()
        await response.background()
        assert store.body.closed and semaphore._value == 1

    asyncio.run(run())


def test_saturated_concurrency_fails_closed(monkeypatch):

    file_id = uuid.uuid4()
    semaphore = asyncio.Semaphore(0)
    request = req(Client(decision(file_id)), semaphore=semaphore)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            stream_authorized(
                request,
                ExemptionRequestFileRequest(
                    kind="exemption_request", request_id=uuid.uuid4(), file_id=file_id
                ),
            )
        )
    assert exc.value.status_code == 429


def test_gateway_app_installs_rate_limiter_by_default():
    from app.file_gateway.main import create_app

    app = create_app()
    assert app.state.download_rate_limiter.allow() is True
