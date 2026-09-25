import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.error_logs import LOKI_MAX_ENTRIES, LOKI_MAX_QUERY_RANGE, LokiQueryError, read_error_logs

LOKI = "http://loki.test:3100"
QUERY_RANGE = f"{LOKI}/loki/api/v1/query_range"


def _loki_response(*records: dict) -> dict:
    return {
        "data": {
            "result": [
                {
                    "stream": {"app": "justice-backend", "log_type": "errors"},
                    "values": [[str(i * 1_000_000_000), json.dumps(r)] for i, r in enumerate(records)],
                }
            ]
        }
    }


@respx.mock
def test_read_error_logs_filters_by_source_and_returns_newest_first():
    respx.get(QUERY_RANGE).mock(
        return_value=httpx.Response(200, json=_loki_response(
            {"ts": "2026-08-28T10:00:00+00:00", "level": "ERROR", "msg": "backend", "request_id": "r1", "logger": "backend.errors"},
            {"ts": "2026-08-28T11:00:00+00:00", "level": "ERROR", "msg": "frontend", "request_id": "r2", "logger": "frontend.errors"},
            {"ts": "2026-08-28T12:00:00+00:00", "level": "ERROR", "msg": "frontend-newer", "request_id": "r3", "logger": "frontend.errors"},
        ))
    )

    result = read_error_logs(LOKI, source="frontend", offset=0, limit=20)

    assert result.total == 2
    assert [item.request_id for item in result.items] == ["r3", "r2"]
    assert all(item.source == "frontend" for item in result.items)


@respx.mock
def test_read_error_logs_ignores_malformed_lines():
    respx.get(QUERY_RANGE).mock(return_value=httpx.Response(200, json={
        "data": {"result": [{"stream": {"app": "justice-backend"}, "values": [["1", "not json"], ["2", json.dumps({"msg": "ok", "logger": "backend.errors"})]]}]}
    }))

    result = read_error_logs(LOKI, source=None, offset=0, limit=20)

    assert result.total == 1
    assert result.items[0].message == "ok"
    assert result.items[0].source == "backend"


@respx.mock
def test_read_error_logs_details_are_the_raw_record_and_keys_are_stable():
    record = {"ts": "2026-08-28T10:00:00+00:00", "level": "ERROR", "msg": "boom", "logger": "backend.errors"}
    respx.get(QUERY_RANGE).mock(return_value=httpx.Response(200, json=_loki_response(record)))

    first = read_error_logs(LOKI, source=None, offset=0, limit=20).items[0]
    second = read_error_logs(LOKI, source=None, offset=0, limit=20).items[0]

    assert first.details == record
    assert first.record_key == second.record_key


@respx.mock
def test_read_error_logs_paginates_after_sorting():
    records = [
        {"ts": f"2026-08-28T{hour:02d}:00:00+00:00", "msg": f"m{hour}", "logger": "backend.errors"}
        for hour in range(5)
    ]
    respx.get(QUERY_RANGE).mock(return_value=httpx.Response(200, json=_loki_response(*records)))

    result = read_error_logs(LOKI, source=None, offset=1, limit=2)

    assert result.total == 5
    assert [item.message for item in result.items] == ["m3", "m2"]


@respx.mock
def test_read_error_logs_applies_from_and_to_filters():
    respx.get(QUERY_RANGE).mock(return_value=httpx.Response(200, json=_loki_response(
        {"ts": "2026-08-28T09:00:00+00:00", "msg": "too-old", "logger": "backend.errors"},
        {"ts": "2026-08-28T10:00:00+00:00", "msg": "in-range", "logger": "backend.errors"},
        {"ts": "2026-08-28T11:00:00+00:00", "msg": "too-new", "logger": "backend.errors"},
    )))

    result = read_error_logs(
        LOKI,
        source=None,
        offset=0,
        limit=20,
        from_ts=datetime(2026, 8, 28, 9, 30, tzinfo=UTC),
        to_ts=datetime(2026, 8, 28, 10, 30, tzinfo=UTC),
    )

    assert [item.message for item in result.items] == ["in-range"]


@respx.mock
def test_read_error_logs_queries_only_the_error_stream_within_loki_limits():
    route = respx.get(QUERY_RANGE).mock(return_value=httpx.Response(200, json=_loki_response()))
    to_ts = datetime(2026, 9, 1, tzinfo=UTC)

    read_error_logs(LOKI, source=None, offset=0, limit=100000, from_ts=datetime(2000, 1, 1, tzinfo=UTC), to_ts=to_ts)

    params = route.calls.last.request.url.params
    # Only the dedicated error-log stream, never the root logger's INFO firehose.
    assert 'log_type="errors"' in params["query"]
    # Loki rejects queries wider than max_query_length (721h by default) and
    # limits above max_entries_limit_per_query (5000 by default).
    start_ns, end_ns = int(params["start"]), int(params["end"])
    assert end_ns == int(to_ts.timestamp() * 1_000_000_000)
    assert end_ns - start_ns <= int(LOKI_MAX_QUERY_RANGE.total_seconds() * 1_000_000_000)
    assert start_ns > 0
    assert int(params["limit"]) <= LOKI_MAX_ENTRIES
    assert params["direction"] == "BACKWARD"


@respx.mock
def test_read_error_logs_without_explicit_range_looks_back_the_max_window():
    route = respx.get(QUERY_RANGE).mock(return_value=httpx.Response(200, json=_loki_response()))

    before = datetime.now(UTC)
    read_error_logs(LOKI, source=None, offset=0, limit=20)

    params = route.calls.last.request.url.params
    start = datetime.fromtimestamp(int(params["start"]) / 1_000_000_000, tz=UTC)
    assert before - LOKI_MAX_QUERY_RANGE - timedelta(seconds=5) <= start <= before - LOKI_MAX_QUERY_RANGE + timedelta(seconds=5)


def test_read_error_logs_returns_empty_when_loki_is_not_configured():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url__regex=r".*").mock(return_value=httpx.Response(500))
        result = read_error_logs("", source=None, offset=0, limit=20)

    assert result.total == 0
    assert result.items == []
    assert not route.called


def test_read_error_logs_with_inverted_range_is_empty_without_querying_loki():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(QUERY_RANGE).mock(return_value=httpx.Response(400))
        result = read_error_logs(
            LOKI,
            source=None,
            offset=0,
            limit=20,
            from_ts=datetime(2026, 8, 28, 12, tzinfo=UTC),
            to_ts=datetime(2026, 8, 28, 11, tzinfo=UTC),
        )

    assert result.total == 0
    assert not route.called


@respx.mock
def test_read_error_logs_raises_loki_query_error_when_loki_fails():
    respx.get(QUERY_RANGE).mock(return_value=httpx.Response(400, text="the query time range exceeds the limit"))

    with pytest.raises(LokiQueryError):
        read_error_logs(LOKI, source=None, offset=0, limit=20)


@respx.mock
def test_read_error_logs_raises_loki_query_error_when_loki_is_unreachable():
    respx.get(QUERY_RANGE).mock(side_effect=httpx.ConnectError("connection refused"))

    with pytest.raises(LokiQueryError):
        read_error_logs(LOKI, source=None, offset=0, limit=20)
