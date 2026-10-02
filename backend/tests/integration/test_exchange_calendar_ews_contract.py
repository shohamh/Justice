"""Real exchangelib serialization through a socket-free HTTP adapter."""

from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from requests import Response

from app.services.exchange_calendar.ews_client import (
    ExchangeCalendarClient,
    JusticeSourceKey,
    build_account,
)
from app.services.exchange_calendar.projection import (
    CalendarSnapshot,
    ProjectedAttendee,
    SourceType,
)

NS = 'xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages" xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"'


def soap(body: str) -> bytes:
    return f'<s:Envelope {NS}><s:Header><t:ServerVersionInfo MajorVersion="15" MinorVersion="1" MajorBuildNumber="0" MinorBuildNumber="0" Version="Exchange2016"/></s:Header><s:Body>{body}</s:Body></s:Envelope>'.encode()


GET_FOLDER = soap('<m:GetFolderResponse><m:ResponseMessages><m:GetFolderResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode><m:Folders><t:Folder><t:FolderId Id="folder-1" ChangeKey="ck-1"/><t:DisplayName>Calendar</t:DisplayName><t:FolderClass>IPF.Appointment</t:FolderClass><t:ChildFolderCount>0</t:ChildFolderCount></t:Folder></m:Folders></m:GetFolderResponseMessage></m:ResponseMessages></m:GetFolderResponse>')
FIND_EMPTY = soap('<m:FindItemResponse><m:ResponseMessages><m:FindItemResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode><m:RootFolder TotalItemsInView="0" IncludesLastItemInRange="true"><t:Items/></m:RootFolder></m:FindItemResponseMessage></m:ResponseMessages></m:FindItemResponse>')
CREATE_OK = soap('<m:CreateItemResponse><m:ResponseMessages><m:CreateItemResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode><m:Items><t:CalendarItem><t:ItemId Id="ews-1" ChangeKey="ck-1"/></t:CalendarItem></m:Items></m:CreateItemResponseMessage></m:ResponseMessages></m:CreateItemResponse>')


@contextmanager
def permit():
    yield


@pytest.mark.parametrize("all_day", [False, True])
def test_create_soap_has_key_zone_attendees_and_invites(monkeypatch, all_day):
    from requests.adapters import HTTPAdapter

    requests = []

    def send(self, request, **kwargs):
        xml = request.body.decode() if isinstance(request.body, bytes) else request.body
        requests.append(xml)
        response = Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "text/xml"
        if "GetFolder" in xml:
            response._content = GET_FOLDER
        elif "FindItem" in xml:
            response._content = FIND_EMPTY
        elif "CreateItem" in xml:
            response._content = CREATE_OK
        else:
            raise AssertionError("Unexpected EWS operation; sockets are prohibited")
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    account = build_account(endpoint="https://invalid.test/EWS/Exchange.asmx", mailbox="svc@example.test", username="svc", password="dummy", auth_type="basic", permit=permit)
    source_id = uuid4()
    snapshot = CalendarSnapshot(
        source_key=f"duty_shift:{source_id}", source_type=SourceType.DUTY_SHIFT, source_id=source_id,
        subject="Duty", start=datetime(2026, 10, 1, 0 if all_day else 8, tzinfo=ZoneInfo("Asia/Jerusalem")),
        end=datetime(2026, 10, 2 if all_day else 1, 0 if all_day else 16, tzinfo=ZoneInfo("Asia/Jerusalem")),
        all_day=all_day, location="HQ", body="Visible note",
        attendees=(ProjectedAttendee("a@example.test", "A", True), ProjectedAttendee("b@example.test", "B", False)),
        problems=(), content_hash="hash",
    )
    ref = ExchangeCalendarClient.from_account(account).upsert(snapshot, None, None)
    assert ref.item_id == "ews-1"
    found = next(xml for xml in requests if "<m:FindItem" in xml)
    assert snapshot.source_key in found and "JusticeSourceKey" in found
    created = next(xml for xml in requests if "CreateItem" in xml)
    assert "SendMeetingInvitations=\"SendToAllAndSaveCopy\"" in created
    assert "Israel Standard Time" in created
    assert "JusticeSourceKey" in created and snapshot.source_key in created
    assert "a@example.test" in created and "b@example.test" in created
    assert "Visible note" in created and "HQ" in created
    from xml.etree import ElementTree as ET
    value = next(element.text for element in ET.fromstring(created).iter() if element.tag.endswith("IsAllDayEvent"))
    assert value == ("1" if all_day else "0")


def test_source_key_registration_is_searchable():
    assert JusticeSourceKey.property_name == "JusticeSourceKey"
    assert JusticeSourceKey.property_type == "String"



def test_update_and_cancel_soap_flags(monkeypatch):
    from exchangelib import CalendarItem
    from requests.adapters import HTTPAdapter

    from app.services.exchange_calendar.ews_client import _ExchangeStore

    update_ok = soap('<m:UpdateItemResponse><m:ResponseMessages><m:UpdateItemResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode><m:Items><t:CalendarItem><t:ItemId Id="ews-1" ChangeKey="ck-2"/></t:CalendarItem></m:Items></m:UpdateItemResponseMessage></m:ResponseMessages></m:UpdateItemResponse>')
    delete_ok = soap('<m:DeleteItemResponse><m:ResponseMessages><m:DeleteItemResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode></m:DeleteItemResponseMessage></m:ResponseMessages></m:DeleteItemResponse>')
    captured = []

    def send(self, request, **kwargs):
        xml = request.body.decode()
        captured.append(xml)
        response = Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "text/xml"
        if "GetFolder" in xml:
            response._content = GET_FOLDER
        elif "UpdateItem" in xml:
            response._content = update_ok
        elif "DeleteItem" in xml:
            response._content = delete_ok
        else:
            raise AssertionError("Unexpected EWS operation; sockets are prohibited")
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    account = build_account(endpoint="https://invalid.test/EWS/Exchange.asmx", mailbox="svc@example.test", username="svc", password="dummy", auth_type="basic", permit=permit)
    item = CalendarItem(
        folder=account.calendar, id="ews-1", changekey="ck-1",
        required_attendees=[], optional_attendees=[],
    )
    source_id = uuid4()
    snapshot = CalendarSnapshot(
        source_key=f"duty_shift:{source_id}", source_type=SourceType.DUTY_SHIFT, source_id=source_id,
        subject="Duty update", start=datetime(2026, 10, 1, 8, tzinfo=ZoneInfo("Asia/Jerusalem")),
        end=datetime(2026, 10, 1, 16, tzinfo=ZoneInfo("Asia/Jerusalem")),
        all_day=False, location="HQ", body="Visible note", attendees=(), problems=(), content_hash="new",
    )
    store = _ExchangeStore(account)
    store.get = lambda item_id: item
    store.find = lambda key: pytest.fail("Known EWS item IDs should be read directly")
    ref = ExchangeCalendarClient(store).upsert(snapshot, "ews-1", "ck-1")
    assert ref.change_key == "ck-2"
    ExchangeCalendarClient(store).cancel(snapshot.source_key, "ews-1")
    update = next(xml for xml in captured if "UpdateItem" in xml)
    deleted = next(xml for xml in captured if "<m:DeleteItem " in xml)
    assert 'SendMeetingInvitationsOrCancellations="SendToAllAndSaveCopy"' in update
    assert 'SendMeetingCancellations="SendToAllAndSaveCopy"' in deleted
    assert snapshot.source_key in update
    assert "FieldURI=\"calendar:RequiredAttendees\"" not in update
    assert "FieldURI=\"calendar:OptionalAttendees\"" not in update


def test_mixed_attendee_and_meeting_changes_send_one_final_invite():
    from types import SimpleNamespace

    from app.services.exchange_calendar.ews_client import _ExchangeStore

    class RecordingItem:
        def __init__(self):
            self.saves = []

        def save(self, **kwargs):
            self.saves.append(kwargs)

    item = RecordingItem()
    _ExchangeStore(SimpleNamespace()).update(
        item,
        ["subject", "required_attendees", "body", "optional_attendees"],
    )

    assert [save["update_fields"] for save in item.saves] == [
        ["required_attendees", "optional_attendees"],
        ["subject", "body"],
    ]
    assert [save["send_meeting_invitations"] for save in item.saves] == [
        "SendToNone",
        "SendToAllAndSaveCopy",
    ]


def test_probe_is_read_only_and_unauthorized_is_reported(monkeypatch):
    from exchangelib.errors import UnauthorizedError
    from requests.adapters import HTTPAdapter

    from app.services.exchange_calendar.ews_client import _ExchangeStore

    captured = []

    def send(self, request, **kwargs):
        xml = request.body.decode()
        captured.append(xml)
        response = Response()
        response.url = request.url
        response.request = request
        if "GetFolder" in xml:
            response.status_code = 200
            response._content = GET_FOLDER
        else:
            response.status_code = 401
            response._content = b"unauthorized"
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    account = build_account(endpoint="https://invalid.test/EWS/Exchange.asmx", mailbox="svc@example.test", username="svc", password="dummy", auth_type="basic", permit=permit)
    client = ExchangeCalendarClient(_ExchangeStore(account))
    try:
        client.probe()
    except UnauthorizedError:
        pass
    else:
        raise AssertionError("Unauthorized response was accepted")
    assert any("FindItem" in xml for xml in captured)
    assert all("CreateItem" not in xml for xml in captured)




def test_server_busy_response_is_raised_without_retry_or_socket(monkeypatch):
    from exchangelib.errors import ErrorServerBusy
    from requests.adapters import HTTPAdapter

    from app.services.exchange_calendar.ews_client import _ExchangeStore

    busy = soap('<m:FindItemResponse><m:ResponseMessages><m:FindItemResponseMessage ResponseClass="Error"><m:MessageText>Busy</m:MessageText><m:ResponseCode>ErrorServerBusy</m:ResponseCode></m:FindItemResponseMessage></m:ResponseMessages></m:FindItemResponse>')
    attempts = []

    def send(self, request, **kwargs):
        xml = request.body.decode()
        attempts.append(xml)
        response = Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "text/xml"
        if "GetFolder" in xml:
            response._content = GET_FOLDER
        elif "FindItem" in xml:
            response._content = busy
        else:
            raise AssertionError("Unexpected EWS operation; sockets are prohibited")
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    account = build_account(endpoint="https://invalid.test/EWS/Exchange.asmx", mailbox="svc@example.test", username="svc", password="dummy", auth_type="basic", permit=permit)
    with pytest.raises(ErrorServerBusy):
        ExchangeCalendarClient(_ExchangeStore(account)).probe()
    assert sum("FindItem" in xml for xml in attempts) == 1



@pytest.mark.parametrize("response_code", ["ErrorTimeoutExpired", "ErrorInternalServerTransientError"])
def test_sdk_transient_soap_errors_enter_worker_retry_path(monkeypatch, response_code):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from exchangelib import errors
    from requests.adapters import HTTPAdapter

    from app.services.exchange_calendar.ews_client import _ExchangeStore
    from app.services.exchange_calendar.worker import ExchangeCalendarWorker

    fault = soap(
        '<m:FindItemResponse><m:ResponseMessages>'
        f'<m:FindItemResponseMessage ResponseClass="Error"><m:MessageText>private</m:MessageText><m:ResponseCode>{response_code}</m:ResponseCode></m:FindItemResponseMessage>'
        '</m:ResponseMessages></m:FindItemResponse>'
    )
    attempts = []

    def send(self, request, **kwargs):
        xml = request.body.decode()
        attempts.append(xml)
        response = Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "text/xml"
        if "GetFolder" in xml:
            response._content = GET_FOLDER
        elif "FindItem" in xml:
            response._content = fault
        else:
            raise AssertionError("Unexpected EWS operation; sockets are prohibited")
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    account = build_account(
        endpoint="https://invalid.test/EWS/Exchange.asmx", mailbox="svc@example.test",
        username="svc", password="dummy", auth_type="basic", permit=permit,
    )
    expected = errors.ErrorServerBusy if response_code == "ErrorInternalServerTransientError" else getattr(errors, response_code)
    with pytest.raises(expected) as raised:
        ExchangeCalendarClient(_ExchangeStore(account)).probe()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    worker = ExchangeCalendarWorker(object(), object(), bootstrap=lambda at: None)
    outcome = worker._failure(raised.value, SimpleNamespace(attempt_count=1), now)
    assert outcome.retry_at is not None and outcome.retry_at > now
    assert sum("<m:FindItem" in xml for xml in attempts) == 1


def test_all_day_getitem_readback_matches_unchanged_snapshot(monkeypatch):
    from datetime import date

    from requests.adapters import HTTPAdapter

    from app.services.exchange_calendar.ews_client import _ExchangeStore

    source_id = uuid4()
    source_key = f"range_event:{source_id}"
    readback = soap(
        '<m:GetItemResponse><m:ResponseMessages>'
        '<m:GetItemResponseMessage ResponseClass="Success"><m:ResponseCode>NoError</m:ResponseCode>'
        '<m:Items><t:CalendarItem><t:ItemId Id="ews-all-day" ChangeKey="ck-1"/>'
        '<t:Subject>Range</t:Subject><t:Body BodyType="Text">Visible</t:Body>'
        '<t:Start>2026-10-01T00:00:00+03:00</t:Start>'
        '<t:End>2026-10-02T00:00:00+03:00</t:End>'
        '<t:IsAllDayEvent>true</t:IsAllDayEvent><t:Location>Range</t:Location>'
        '<t:ExtendedProperty><t:ExtendedFieldURI PropertySetId="5c6b2f3d-1bc4-4c52-95d3-43c3b1371291" '
        'PropertyName="JusticeSourceKey" PropertyType="String"/>'
        f'<t:Value>{source_key}</t:Value></t:ExtendedProperty>'
        '</t:CalendarItem></m:Items></m:GetItemResponseMessage></m:ResponseMessages></m:GetItemResponse>'
    )
    attempts = []

    def send(self, request, **kwargs):
        xml = request.body.decode()
        attempts.append(xml)
        response = Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "text/xml"
        if "<m:GetFolder" in xml:
            response._content = GET_FOLDER
        elif "<m:GetItem" in xml:
            response._content = readback
        else:
            raise AssertionError("Unexpected EWS operation; sockets are prohibited")
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    account = build_account(
        endpoint="https://invalid.test/EWS/Exchange.asmx", mailbox="svc@example.test",
        username="svc", password="dummy", auth_type="basic", permit=permit,
    )
    client = ExchangeCalendarClient(_ExchangeStore(account))
    snapshot = CalendarSnapshot(
        source_key=source_key, source_type=SourceType.RANGE_EVENT, source_id=source_id,
        subject="Range",
        start=datetime(2026, 10, 1, 0, tzinfo=ZoneInfo("Asia/Jerusalem")),
        end=datetime(2026, 10, 2, 0, tzinfo=ZoneInfo("Asia/Jerusalem")),
        all_day=True, location="Range", body="Visible",
        attendees=(), problems=(), content_hash="same",
    )
    item = client.store.get("ews-all-day")
    assert item.is_all_day is True
    assert item.start == date(2026, 10, 1)
    assert item.end == date(2026, 10, 1)
    assert client.matches(snapshot, "ews-all-day") is True
    assert len([xml for xml in attempts if "<m:GetItem" in xml]) == 2


def test_timed_getitem_readback_matches_after_server_drops_subsecond_precision():
    from types import SimpleNamespace

    from exchangelib import CalendarItem, EWSDateTime

    source_id = uuid4()
    source_key = f"duty_shift:{source_id}"
    start = datetime(2026, 10, 3, 8, 0, 0, 777_000, tzinfo=ZoneInfo("Asia/Jerusalem"))
    end = datetime(2026, 10, 3, 9, 0, 0, 777_000, tzinfo=ZoneInfo("Asia/Jerusalem"))
    snapshot = CalendarSnapshot(
        source_key=source_key,
        source_type=SourceType.DUTY_SHIFT,
        source_id=source_id,
        subject="Duty",
        start=start,
        end=end,
        all_day=False,
        location="HQ",
        body="Visible note",
        attendees=(),
        problems=(),
        content_hash="same",
    )
    item = CalendarItem(
        id="ews-timed",
        subject="Duty",
        start=EWSDateTime.from_datetime(start).replace(microsecond=0),
        end=EWSDateTime.from_datetime(end).replace(microsecond=0),
        is_all_day=False,
        location="HQ",
        body="Visible note",
        justice_source_key=source_key,
        required_attendees=[],
        optional_attendees=[],
    )
    client = ExchangeCalendarClient(SimpleNamespace(get=lambda item_id: item))

    assert client.matches(snapshot, "ews-timed") is True
