from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.storage.reconciliation import reconcile_storage


class FakeMaintenanceStorage:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self.deleted: list[str] = []
        self.fail_delete = False

    def iter_keys(self, *, prefix: str):
        yield from (key for key in self.keys if key.startswith(prefix))

    def iter_objects(self, *, prefix: str):
        old = datetime.now(UTC) - timedelta(days=3)
        yield from ((key, old) for key in self.keys if key.startswith(prefix))

    def delete(self, *, key: str) -> None:
        self.deleted.append(key)
        if self.fail_delete:
            raise RuntimeError("private delete detail")

    def head(self, *, key: str):
        return None


class FakeSession:
    def __init__(self, referenced: set[str], pending_outbox=()) -> None:
        self.referenced = referenced
        self.pending_outbox = list(pending_outbox)
        self.commits = 0

    def referenced_storage_keys(self) -> set[str]:
        return self.referenced

    def pending_delete_outbox(self):
        return self.pending_outbox

    def commit(self) -> None:
        self.commits += 1


def test_reconciliation_discovers_old_orphan_without_touching_live_references() -> None:
    orphan = "gimelim/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    referenced = "gimelim/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    storage = FakeMaintenanceStorage([orphan, referenced])
    session = FakeSession({referenced})

    report = reconcile_storage(
        session,
        storage,
        older_than_hours=24,
        now=datetime.now(UTC) + timedelta(days=2),
        delete_orphans=False,
    )

    assert report.orphan_keys == [orphan]
    assert report.missing_references == []
    assert storage.deleted == []


def test_outbox_retries_only_from_maintenance_reconciler() -> None:
    key = "gimelim/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    storage = FakeMaintenanceStorage([])
    outbox = type(
        "OutboxItem",
        (),
        {"object_key": key, "attempts": 0, "last_error_code": None, "completed_at": None},
    )()
    session = FakeSession(set(), [outbox])

    report = reconcile_storage(session, storage, older_than_hours=24, delete_orphans=True)

    assert report.outbox_completed == 1
    assert storage.deleted == [key]
    assert outbox.attempts == 1
    assert outbox.completed_at is not None
    assert session.commits == 1




def test_dry_run_leaves_delete_outbox_pending() -> None:
    key = "gimelim/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    storage = FakeMaintenanceStorage([])
    outbox = type("OutboxItem", (), {"object_key": key, "attempts": 0, "last_error_code": None, "completed_at": None})()
    session = FakeSession(set(), [outbox])

    report = reconcile_storage(
        session, storage, older_than_hours=24, delete_orphans=False, process_outbox=False
    )

    assert report.outbox_completed == 0
    assert outbox.attempts == 0
    assert storage.deleted == []
    assert session.commits == 0


def test_orphan_delete_failure_is_reported_without_raw_provider_error() -> None:
    key = "gimelim/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    storage = FakeMaintenanceStorage([key])
    storage.fail_delete = True
    report = reconcile_storage(FakeSession(set()), storage, older_than_hours=24)

    assert report.orphan_delete_failed == 1
    assert "private delete detail" not in repr(report)
