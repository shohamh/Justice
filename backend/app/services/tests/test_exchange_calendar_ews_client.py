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
