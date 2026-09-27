import asyncio
import threading
import uuid

import pytest
from fastapi import HTTPException

from app.file_authorization.schemas import ExemptionRequestFileRequest, FileAuthorizationDecision
from app.file_gateway.main import create_app
from app.file_gateway.routes import stream_authorized
from app.storage.keys import make_object_key


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.request_id = None

    async def authorize(self, request, token, request_id=None):
        self.request_id = request_id
        return self.result


def decision(file_id):
    return FileAuthorizationDecision(
        object_key=make_object_key("exemption_request", file_id),
        sha256="a" * 64,
        size=5,
        content_type="text/plain",
        filename="a.txt",
    )


class DisconnectBody:
    def __init__(self):
        self.started = threading.Event()
        self.closed_event = threading.Event()
        self.closed = False
        self.reads = 0

    def read(self, size):
        self.reads += 1
        if self.reads == 1:
            self.started.set()
            return b"hello"
        self.closed_event.wait(2)
        return b""

    def close(self):
        self.closed = True
        self.closed_event.set()


class Store:
    def __init__(self, body):
        self.body = body

    def open_read(self, *, key):
        return self.body, 5


def test_asgi_disconnect_closes_body_and_releases_semaphore(monkeypatch):
    import app.file_gateway.routes as routes

    file_id = uuid.uuid4()
    request_id = uuid.uuid4()
    body = DisconnectBody()
    client = FakeClient(decision(file_id))
    monkeypatch.setattr(routes, "get_object_storage", lambda: Store(body))
    app = create_app()
    semaphore = asyncio.Semaphore(1)
    app.state.download_semaphore = semaphore
    app.state.authorization_client = client
    path = f"/api/file-download/exemption-requests/{uuid.uuid4()}/files/{file_id}"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"authorization", b"Bearer test-token"),
            (b"x-request-id", str(request_id).encode()),
        ],
        "client": ("test", 123),
        "server": ("test", 80),
    }
    received_request = False
    sent = []

    async def receive():
        nonlocal received_request
        if not received_request:
            received_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.to_thread(body.started.wait, 1)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def run():
        await app(scope, receive, send)
        assert body.closed
        assert semaphore._value == 1
        assert client.request_id == str(request_id)
        assert any(event["type"] == "http.response.start" for event in sent)

    asyncio.run(run())


def test_late_open_read_result_is_closed_after_timeout_and_permit_released(monkeypatch):
    import app.file_gateway.routes as routes

    release_open = threading.Event()

    class LateBody:
        closed = False

        def close(self):
            self.closed = True

    body = LateBody()

    class SlowStore:
        def open_read(self, *, key):
            release_open.wait(2)
            return body, 5

    monkeypatch.setattr(routes, "get_object_storage", lambda: SlowStore())
    monkeypatch.setattr(routes, "_OPEN_READ_TIMEOUT_SECONDS", 0.01)
    file_id = uuid.uuid4()
    request = ExemptionRequestFileRequest(
        kind="exemption_request", request_id=uuid.uuid4(), file_id=file_id
    )
    client = FakeClient(decision(file_id))
    app = create_app()
    semaphore = asyncio.Semaphore(1)
    app.state.download_semaphore = semaphore
    app.state.authorization_client = client

    async def run():
        from starlette.requests import Request

        request_obj = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(b"authorization", b"Bearer token")],
                "query_string": b"",
                "app": app,
            }
        )
        with pytest.raises(HTTPException) as exc:
            await stream_authorized(request_obj, request)
        assert exc.value.status_code == 503
        assert semaphore._value == 1
        release_open.set()
        for _ in range(100):
            if body.closed:
                break
            await asyncio.sleep(0.01)
        assert body.closed

    asyncio.run(run())
