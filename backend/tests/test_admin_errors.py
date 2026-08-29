import json

from app.error_logs import read_error_logs


def test_read_error_logs_returns_newest_entries_from_both_sources_with_filters(tmp_path):
    (tmp_path / "backend-errors.log").write_text(
        json.dumps({"ts": "2026-08-28T10:00:00+00:00", "level": "ERROR", "msg": "backend", "request_id": "r1"}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "frontend-errors.log").write_text(
        json.dumps({"ts": "2026-08-28T11:00:00+00:00", "level": "ERROR", "msg": "frontend", "request_id": "r2"}) + "\n",
        encoding="utf-8",
    )

    result = read_error_logs(tmp_path, source="frontend", offset=0, limit=20)

    assert result.total == 1
    assert result.items[0].source == "frontend"
    assert result.items[0].request_id == "r2"


def test_read_error_logs_ignores_malformed_lines(tmp_path):
    (tmp_path / "backend-errors.log").write_text("not json\n" + json.dumps({"msg": "ok"}) + "\n", encoding="utf-8")
    result = read_error_logs(tmp_path, source=None, offset=0, limit=20)
    assert result.total == 1
    assert result.items[0].message == "ok"
