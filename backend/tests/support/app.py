"""Test-only FastAPI lifecycle and process-state helpers."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient


class _TestObjectStorage:
    """Per-app in-memory store for integration tests; never touches S3."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, *, key: str, data: bytes, content_type: str, sha256: str):
        self.objects[key] = data
        from app.storage.protocol import StoredObject

        return StoredObject(key, len(data), sha256, None, None)

    def open_read(self, *, key: str):
        data = self.objects[key]
        return BytesIO(data), len(data)

    def head(self, *, key: str):
        data = self.objects.get(key)
        if data is None:
            return None
        from app.storage.protocol import StoredObject

        return StoredObject(key, len(data), sha256(data).hexdigest(), None, None)


def reset_process_state() -> None:
    """Clear the mutable in-memory state that can leak between test clients.

    The SlowAPI storage is the only application process state currently
    identified as test-shared. Database state is reset by the database adapter.
    """
    from app.rate_limit import limiter

    limiter._storage.reset()


@contextmanager
def test_app() -> Iterator[FastAPI]:
    """Create a test application while suppressing production workers."""
    previous_testing = os.environ.get("JUSTICE_TESTING")
    os.environ["JUSTICE_TESTING"] = "1"
    try:
        from app.main import create_app
        from app.storage.dependencies import get_object_storage

        app = create_app()
        storage = _TestObjectStorage()
        app.dependency_overrides[get_object_storage] = lambda: storage
        yield app
    finally:
        if previous_testing is None:
            os.environ.pop("JUSTICE_TESTING", None)
        else:
            os.environ["JUSTICE_TESTING"] = previous_testing


@contextmanager
def test_client() -> Iterator[TestClient]:
    """Create one isolated client and lifespan invocation for a test."""
    reset_process_state()
    try:
        with test_app() as app, TestClient(app) as client:
            yield client
    finally:
        reset_process_state()
