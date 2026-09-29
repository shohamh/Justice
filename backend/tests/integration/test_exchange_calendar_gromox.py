"""Disposable Gromox smoke test. Never runs without an explicit opt-in."""

import os
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.exchange_integration


def _exercise_meeting_lifecycle(client, snapshot):
    """Exercise disposable meeting recovery and always attempt cleanup."""
    latest_id = None
    try:
        created = client.upsert(snapshot, None, None)
        latest_id = created.item_id
        assert client.matches(snapshot, latest_id)
        updated = replace(
            snapshot,
            subject=snapshot.subject + " updated",
            body=snapshot.body + " updated",
            content_hash=snapshot.content_hash + "-updated",
        )
        ref = client.upsert(updated, latest_id, created.change_key)
        latest_id = ref.item_id
        assert client.matches(updated, latest_id)
        client.cancel(snapshot.source_key, latest_id)
        assert client.store.find(snapshot.source_key) is None
    finally:
        client.cancel(snapshot.source_key, latest_id)


def test_disposable_gromox_lifecycle():
    if os.getenv("JUSTICE_TEST_GROMOX_ENABLED") != "1":
        pytest.skip("Gromox integration is opt-in")
    names = (
        "JUSTICE_TEST_GROMOX_ENDPOINT",
        "JUSTICE_TEST_GROMOX_MAILBOX",
        "JUSTICE_TEST_GROMOX_USERNAME",
        "JUSTICE_TEST_GROMOX_PASSWORD",
        "JUSTICE_TEST_GROMOX_ATTENDEE",
    )
    if not all(os.getenv(name) for name in names):
        pytest.skip("Disposable Gromox endpoint and mailbox secrets are absent")
    # A local gate is sufficient for this disposable, single-process smoke run.
    # Production uses DatabaseGate in app.exchange_calendar_worker.
    from app.services.exchange_calendar.ews_client import ExchangeCalendarClient, build_account
    from app.services.exchange_calendar.rate_limiter import ExchangeRateLimiter, InMemoryGate

    account = build_account(
        endpoint=os.environ[names[0]], mailbox=os.environ[names[1]],
        username=os.environ[names[2]], password=os.environ[names[3]],
        auth_type=os.getenv("JUSTICE_TEST_GROMOX_AUTH_TYPE") or None,
        permit=ExchangeRateLimiter(InMemoryGate()).permit,
    )
    from app.services.exchange_calendar.projection import (
        CalendarSnapshot,
        ProjectedAttendee,
        SourceType,
    )

    client = ExchangeCalendarClient.from_account(account)
    client.probe()
    source_id = uuid4()
    start = datetime.now(ZoneInfo("Asia/Jerusalem")) + timedelta(days=1)
    snapshot = CalendarSnapshot(
        source_key=f"duty_shift:{source_id}",
        source_type=SourceType.DUTY_SHIFT,
        source_id=source_id,
        subject=f"Justice disposable Gromox {source_id}",
        start=start,
        end=start + timedelta(hours=1),
        all_day=False,
        location="Disposable Gromox calendar",
        body="Disposable integration check",
        attendees=(ProjectedAttendee(os.environ[names[4]], "Disposable attendee", True),),
        problems=(),
        content_hash=str(source_id),
    )
    _exercise_meeting_lifecycle(client, snapshot)



def test_lifecycle_helper_creates_reads_updates_cancels_and_cleans_up():
    from dataclasses import dataclass
    from types import SimpleNamespace

    from tests.integration.test_exchange_calendar_gromox import _exercise_meeting_lifecycle

    @dataclass(frozen=True)
    class Snapshot:
        source_key: str = "duty_shift:disposable"
        subject: str = "Disposable"
        body: str = "Initial"
        content_hash: str = "one"

    class FakeClient:
        def __init__(self):
            self.remote = None
            self.calls = []
            self.store = self

        def upsert(self, snapshot, item_id, change_key):
            self.calls.append("create" if item_id is None else "update")
            self.remote = snapshot
            return SimpleNamespace(item_id="ews-1", change_key="ck-1")

        def matches(self, snapshot, item_id):
            self.calls.append("read")
            return self.remote == snapshot

        def find(self, source_key):
            self.calls.append("find")
            return self.remote

        def cancel(self, source_key, item_id):
            self.calls.append("cancel")
            self.remote = None

    client = FakeClient()
    _exercise_meeting_lifecycle(client, Snapshot())
    assert client.calls == ["create", "read", "update", "read", "cancel", "find", "cancel"]
    assert client.remote is None


def test_lifecycle_cleanup_runs_after_update_failure():
    from dataclasses import dataclass
    from types import SimpleNamespace

    from tests.integration.test_exchange_calendar_gromox import _exercise_meeting_lifecycle

    @dataclass(frozen=True)
    class Snapshot:
        source_key: str = "duty_shift:disposable"
        subject: str = "Disposable"
        body: str = "Initial"
        content_hash: str = "one"

    class FakeClient:
        def __init__(self):
            self.cancelled = False

        def upsert(self, snapshot, item_id, change_key):
            if item_id is not None:
                raise RuntimeError("update failed")
            return SimpleNamespace(item_id="ews-1", change_key="ck-1")

        def matches(self, snapshot, item_id):
            return True

        def cancel(self, source_key, item_id):
            self.cancelled = True

    client = FakeClient()
    with pytest.raises(RuntimeError, match="update failed"):
        _exercise_meeting_lifecycle(client, Snapshot())
    assert client.cancelled


def test_lifecycle_rejects_lingering_source_key_after_cancel():
    from dataclasses import dataclass
    from types import SimpleNamespace

    @dataclass(frozen=True)
    class Snapshot:
        source_key: str = "duty_shift:disposable"
        subject: str = "Disposable"
        body: str = "Initial"
        content_hash: str = "one"

    class FakeClient:
        def __init__(self):
            self.remote = None
            self.store = self
            self.cancel_calls = 0

        def upsert(self, snapshot, item_id, change_key):
            self.remote = snapshot
            return SimpleNamespace(item_id="ews-1", change_key="ck-1")

        def matches(self, snapshot, item_id):
            return self.remote == snapshot and self.cancel_calls == 0

        def find(self, source_key):
            return self.remote

        def cancel(self, source_key, item_id):
            self.cancel_calls += 1
            if self.cancel_calls > 1:
                self.remote = None

    with pytest.raises(AssertionError):
        _exercise_meeting_lifecycle(FakeClient(), Snapshot())
