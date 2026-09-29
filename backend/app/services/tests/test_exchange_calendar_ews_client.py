from app.services.exchange_calendar.ews_client import ExchangeCalendarClient


def test_client_exists():
    assert ExchangeCalendarClient



def test_create_adopts_source_key_and_maps_fields():
    from datetime import datetime
    from uuid import uuid4
    from zoneinfo import ZoneInfo

    from app.services.exchange_calendar.projection import (
        CalendarSnapshot,
        ProjectedAttendee,
        SourceType,
    )

    key = f"duty_shift:{uuid4()}"
    snapshot = CalendarSnapshot(
        source_key=key, source_type=SourceType.DUTY_SHIFT, source_id=uuid4(),
        subject="Duty", start=datetime(2026, 10, 1, 8, tzinfo=ZoneInfo("Asia/Jerusalem")),
        end=datetime(2026, 10, 1, 16, tzinfo=ZoneInfo("Asia/Jerusalem")),
        all_day=False, location="HQ", body="Visible note",
        attendees=(ProjectedAttendee("a@example.test", "A", True), ProjectedAttendee("b@example.test", "B", False)),
        problems=(), content_hash="hash",
    )

    class Store:
        def __init__(self):
            self.items = {}
            self.creates = 0

        def find(self, source_key):
            return self.items.get(source_key)

        def create(self, item):
            self.creates += 1
            assert item.justice_source_key == key
            assert item.start.tzinfo.ms_id == "Israel Standard Time"
            assert item.location == "HQ" and item.body == "Visible note"
            assert len(item.required_attendees) == len(item.optional_attendees) == 1
            item.id, item.changekey = "ews-1", "ck-1"
            self.items[key] = item
            return item

        def update(self, item):
            item.changekey = "ck-2"
            return item

    store = Store()
    client = ExchangeCalendarClient(store)
    created = client.upsert(snapshot, None, None)
    adopted = client.upsert(snapshot, None, None)
    assert (created.action, adopted.action, store.creates) == ("created", "updated", 1)
    assert adopted.item_id == "ews-1"



def test_missing_stored_item_is_recreated_and_missing_cancel_completes():
    from exchangelib.errors import ErrorItemNotFound

    class Store:
        def __init__(self):
            self.creates = 0

        def find(self, key):
            return None

        def get(self, item_id):
            raise ErrorItemNotFound("gone")

        def create(self, item):
            self.creates += 1
            item.id, item.changekey = "replacement", "ck-new"
            return item

    from datetime import datetime
    from uuid import uuid4
    from zoneinfo import ZoneInfo

    from app.services.exchange_calendar.projection import CalendarSnapshot, SourceType

    source_id = uuid4()
    snapshot = CalendarSnapshot(
        source_key=f"duty_shift:{source_id}", source_type=SourceType.DUTY_SHIFT,
        source_id=source_id, subject="Duty",
        start=datetime(2026, 10, 1, 8, tzinfo=ZoneInfo("Asia/Jerusalem")),
        end=datetime(2026, 10, 1, 16, tzinfo=ZoneInfo("Asia/Jerusalem")),
        all_day=False, location="HQ", body="", attendees=(), problems=(), content_hash="hash",
    )
    store = Store()
    client = ExchangeCalendarClient(store)
    assert client.upsert(snapshot, "deleted-id", "old-ck").item_id == "replacement"
    assert store.creates == 1
    client.cancel(snapshot.source_key, "deleted-id")


def test_remote_match_detects_manual_edit_and_deletion():
    from datetime import datetime
    from types import SimpleNamespace
    from uuid import uuid4
    from zoneinfo import ZoneInfo

    from exchangelib.errors import ErrorItemNotFound

    from app.services.exchange_calendar.projection import CalendarSnapshot, SourceType

    source_id = uuid4()
    start = datetime(2026, 10, 1, 8, tzinfo=ZoneInfo("Asia/Jerusalem"))
    end = datetime(2026, 10, 1, 16, tzinfo=ZoneInfo("Asia/Jerusalem"))
    snapshot = CalendarSnapshot(
        source_key=f"duty_shift:{source_id}", source_type=SourceType.DUTY_SHIFT,
        source_id=source_id, subject="Duty", start=start, end=end,
        all_day=False, location="HQ", body="Notes", attendees=(),
        problems=(), content_hash="hash",
    )

    class Store:
        def __init__(self):
            self.remote = SimpleNamespace(
                justice_source_key=snapshot.source_key, subject="Duty",
                start=start, end=end, is_all_day=False, location="HQ",
                body="Notes", required_attendees=[], optional_attendees=[],
            )

        def get(self, item_id):
            if self.remote is None:
                raise ErrorItemNotFound("gone")
            return self.remote

    store = Store()
    client = ExchangeCalendarClient(store)
    assert client.matches(snapshot, "ews") is True
    store.remote.body = "Manual edit"
    assert client.matches(snapshot, "ews") is False
    store.remote = None
    assert client.matches(snapshot, "ews") is False
