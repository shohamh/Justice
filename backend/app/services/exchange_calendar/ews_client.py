"""On-premises Exchange calendar I/O; used only by the independent worker."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
from exchangelib.errors import ErrorItemNotFound
from exchangelib.protocol import BaseProtocol

from app.services.exchange_calendar.lease import assert_lease_owned
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

    def update(self, item: CalendarItem, update_fields: list[str]):
        attendee_fields = [
            field for field in update_fields
            if field in {"required_attendees", "optional_attendees"}
        ]
        meeting_fields = [field for field in update_fields if field not in attendee_fields]
        if meeting_fields and attendee_fields:
            # Save attendee changes without notifications first, then send one
            # meeting update with the complete current event to all attendees.
            item.save(update_fields=attendee_fields, send_meeting_invitations="SendToNone")
            item.save(
                update_fields=meeting_fields,
                send_meeting_invitations="SendToAllAndSaveCopy",
            )
        else:
            item.save(
                update_fields=update_fields,
                send_meeting_invitations="SendToAllAndSaveCopy",
            )
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
    def _same_time(remote: object, local: datetime) -> bool:
        if not isinstance(remote, datetime) or remote.tzinfo is None:
            return False
        # EWS readbacks may drop subsecond precision.
        remote_time = remote.astimezone(ISRAEL_EWS).replace(microsecond=0)
        local_time = ExchangeCalendarClient._time(local).replace(microsecond=0)
        return remote_time == local_time

    @staticmethod
    def _attendee_emails(attendees) -> list[str]:
        return sorted(
            attendee.mailbox.email_address.strip().lower()
            for attendee in (attendees or ())
        )

    @staticmethod
    def _fill(item: CalendarItem, snapshot: CalendarSnapshot) -> list[str]:
        changed_fields = []
        if item.subject != snapshot.subject:
            item.subject = snapshot.subject
            changed_fields.append("subject")

        if snapshot.all_day:
            start_date = snapshot.start.astimezone(ISRAEL_EWS).date()
            end_date = snapshot.end.astimezone(ISRAEL_EWS).date() - timedelta(days=1)
            start_matches = (
                isinstance(item.start, date) and not isinstance(item.start, datetime)
                and item.start == start_date
            )
            end_matches = (
                isinstance(item.end, date) and not isinstance(item.end, datetime)
                and item.end == end_date
            )
        else:
            start_matches = ExchangeCalendarClient._same_time(item.start, snapshot.start)
            end_matches = ExchangeCalendarClient._same_time(item.end, snapshot.end)

        if not start_matches:
            item.start = ExchangeCalendarClient._time(snapshot.start)
            changed_fields.append("start")
        if not end_matches:
            item.end = ExchangeCalendarClient._time(snapshot.end)
            changed_fields.append("end")
        if bool(item.is_all_day) != snapshot.all_day:
            item.is_all_day = snapshot.all_day
            changed_fields.append("is_all_day")
        if (item.location or "") != snapshot.location:
            item.location = snapshot.location
            changed_fields.append("location")
        if str(item.body or "") != snapshot.body:
            item.body = snapshot.body
            changed_fields.append("body")

        required_attendees = [
            Attendee(mailbox=Mailbox(name=a.display_name, email_address=a.email))
            for a in snapshot.attendees if a.required
        ]
        optional_attendees = [
            Attendee(mailbox=Mailbox(name=a.display_name, email_address=a.email))
            for a in snapshot.attendees if not a.required
        ]
        expected_required = sorted(a.email.strip().lower() for a in snapshot.attendees if a.required)
        expected_optional = sorted(a.email.strip().lower() for a in snapshot.attendees if not a.required)
        if ExchangeCalendarClient._attendee_emails(item.required_attendees) != expected_required:
            item.required_attendees = required_attendees
            changed_fields.append("required_attendees")
        if ExchangeCalendarClient._attendee_emails(item.optional_attendees) != expected_optional:
            item.optional_attendees = optional_attendees
            changed_fields.append("optional_attendees")
        if item.justice_source_key != snapshot.source_key:
            item.justice_source_key = snapshot.source_key
            changed_fields.append("justice_source_key")
        return changed_fields

    def upsert(
        self, snapshot: CalendarSnapshot, existing_item_id: str | None,
        existing_change_key: str | None,
    ) -> ExchangeItemRef:
        # Prefer a fresh read by the persisted ID. The stable-key search is
        # still needed to recover a CreateItem whose ID was never committed.
        item = None
        if existing_item_id:
            with suppress(ErrorItemNotFound):
                item = self.store.get(existing_item_id)
        if item is None:
            item = self.store.find(snapshot.source_key)
        if item is None:
            assert_lease_owned()
            item = CalendarItem()
            self._fill(item, snapshot)
            item = self.store.create(item)
            action = "created"
        else:
            assert_lease_owned()
            update_fields = self._fill(item, snapshot)
            if update_fields:
                item = self.store.update(item, update_fields)
                action = "updated"
            else:
                action = "unchanged"
        return ExchangeItemRef(item_id=item.id, change_key=item.changekey, action=action)

    def matches(self, snapshot: CalendarSnapshot, item_id: str) -> bool:
        """Read remote meeting fields during reconciliation, including deletions."""
        try:
            item = self.store.get(item_id)
        except ErrorItemNotFound:
            return False
        if item is None:
            return False

        if snapshot.all_day:
            # exchangelib parses GetItem all-day boundaries as dates, with an
            # inclusive end date. Our snapshots use an exclusive end midnight.
            start_date = snapshot.start.astimezone(ISRAEL_EWS).date()
            end_date = snapshot.end.astimezone(ISRAEL_EWS).date() - timedelta(days=1)
            times_match = (
                isinstance(item.start, date) and not isinstance(item.start, datetime)
                and isinstance(item.end, date) and not isinstance(item.end, datetime)
                and item.start == start_date and item.end == end_date
            )
        else:
            times_match = (
                ExchangeCalendarClient._same_time(item.start, snapshot.start)
                and ExchangeCalendarClient._same_time(item.end, snapshot.end)
            )

        return (
            item.justice_source_key == snapshot.source_key
            and item.subject == snapshot.subject
            and times_match
            and bool(item.is_all_day) == snapshot.all_day
            and (item.location or "") == snapshot.location
            and str(item.body or "") == snapshot.body
            and ExchangeCalendarClient._attendee_emails(item.required_attendees)
            == sorted(a.email.strip().lower() for a in snapshot.attendees if a.required)
            and ExchangeCalendarClient._attendee_emails(item.optional_attendees)
            == sorted(a.email.strip().lower() for a in snapshot.attendees if not a.required)
        )

    def cancel(self, source_key: str, item_id: str | None) -> None:
        item = None
        if item_id:
            with suppress(ErrorItemNotFound):
                item = self.store.get(item_id)
        if item is None:
            item = self.store.find(source_key)
        if item is not None:
            try:
                assert_lease_owned()
                self.store.delete(item)
            except ErrorItemNotFound:
                # A successful prior DeleteItem may have lost its local commit.
                return

    def probe(self) -> None:
        self.store.probe()
