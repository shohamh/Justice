"""Test-only FastAPI lifecycle and process-state helpers."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient


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

        yield create_app()
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
