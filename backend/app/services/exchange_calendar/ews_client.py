"""On-premises Exchange calendar I/O; used only by the independent worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from exchangelib import (
    DELEGATE,
    Account,
    Attendee,
    Build,
    CalendarItem,
    Configuration,
    Credentials,
    EWSDateTime,
    EWSTimeZone,
    ExtendedProperty,
    FailFast,
    Mailbox,
    Version,
)
from exchangelib.protocol import BaseProtocol

from app.services.exchange_calendar.projection import CalendarSnapshot
from app.services.exchange_calendar.rate_limiter import RateLimitedHTTPAdapter


class JusticeSourceKey(ExtendedProperty):
    """Searchable stable identity for adoption after a local commit failure."""

    property_set_id = "5c6b2f3d-1bc4-4c52-95d3-43c3b1371291"
    property_name = "JusticeSourceKey"
    property_type = "String"


CalendarItem.register("justice_source_key", JusticeSourceKey)
ISRAEL_EWS = EWSTimeZone.from_timezone(ZoneInfo("Asia/Jerusalem"))


@dataclass(frozen=True)
class ExchangeItemRef:
    item_id: str
    change_key: str | None
    action: str


def build_account(
    *, endpoint: str, mailbox: str, username: str, password: str,
    auth_type: str | None = None, permit=None,
) -> Account:
    """Construct an explicit-endpoint, non-autodiscovery service mailbox."""
    if not all((endpoint, mailbox, username, password)):
        raise ValueError("Exchange endpoint, mailbox, username and password are required")
    if permit is None:
        raise ValueError("Exchange HTTP request gate is required")

    class _GatedAdapter(RateLimitedHTTPAdapter):
        permit_factory = staticmethod(permit)

    BaseProtocol.HTTP_ADAPTER_CLS = _GatedAdapter
    config = Configuration(
        service_endpoint=endpoint,
        credentials=Credentials(username=username, password=password),
        auth_type=auth_type,
        version=Version(Build(15, 1)),
        retry_policy=FailFast(),
    )
    return Account(
        primary_smtp_address=mailbox,
        config=config,
        autodiscover=False,
        access_type=DELEGATE,
        default_timezone=ISRAEL_EWS,
    )


class _ExchangeStore:
    def __init__(self, account: Account):
        self.account = account

    def find(self, source_key: str):
        return next(iter(self.account.calendar.filter(justice_source_key=source_key)[:1]), None)

    def get(self, item_id: str):
        return self.account.calendar.get(id=item_id)

    def create(self, item: CalendarItem):
        item.account = self.account
        item.folder = self.account.calendar
        item.save(send_meeting_invitations="SendToAllAndSaveCopy")
        return item

    def update(self, item: CalendarItem):
        item.save(send_meeting_invitations="SendToAllAndSaveCopy")
        return item

    def delete(self, item: CalendarItem):
        item.delete(send_meeting_cancellations="SendToAllAndSaveCopy")

    def probe(self):
        # FindItem checks credentials and mailbox reachability without creating data.
        list(self.account.calendar.all().only("id")[:1])


class ExchangeCalendarClient:
    def __init__(self, store: object):
        self.store = store

    @classmethod
    def from_account(cls, account: Account) -> ExchangeCalendarClient:
        return cls(_ExchangeStore(account))

    @staticmethod
    def _time(value: datetime) -> EWSDateTime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Calendar snapshot times must be timezone-aware")
        return EWSDateTime.from_datetime(value).astimezone(ISRAEL_EWS)

    @staticmethod
    def _fill(item: CalendarItem, snapshot: CalendarSnapshot) -> None:
        item.subject = snapshot.subject
        item.start = ExchangeCalendarClient._time(snapshot.start)
        item.end = ExchangeCalendarClient._time(snapshot.end)
        item.is_all_day = snapshot.all_day
        item.location = snapshot.location
        item.body = snapshot.body
        item.required_attendees = [
            Attendee(mailbox=Mailbox(name=a.display_name, email_address=a.email))
            for a in snapshot.attendees if a.required
        ]
        item.optional_attendees = [
            Attendee(mailbox=Mailbox(name=a.display_name, email_address=a.email))
            for a in snapshot.attendees if not a.required
        ]
        item.justice_source_key = snapshot.source_key

    def upsert(
        self, snapshot: CalendarSnapshot, existing_item_id: str | None,
        existing_change_key: str | None,
    ) -> ExchangeItemRef:
        # Always search before create. A previous CreateItem may have succeeded
        # even when persisting its new ID in Justice failed.
        item = self.store.find(snapshot.source_key)
        if item is None and existing_item_id:
            item = self.store.get(existing_item_id)
        if item is None:
            item = CalendarItem()
            self._fill(item, snapshot)
            item = self.store.create(item)
            action = "created"
        else:
            self._fill(item, snapshot)
            item = self.store.update(item)
            action = "updated"
        return ExchangeItemRef(item_id=item.id, change_key=item.changekey, action=action)

    def cancel(self, source_key: str, item_id: str | None) -> None:
        item = self.store.find(source_key)
        if item is None and item_id:
            item = self.store.get(item_id)
        if item is not None:
            self.store.delete(item)

    def probe(self) -> None:
        self.store.probe()
