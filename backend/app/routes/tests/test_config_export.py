from __future__ import annotations

import json

import openpyxl
import pytest
from sqlalchemy import delete, select

from app.db.models import BugReport, SystemSetting
from app.routes.config_export import _write_bug_reports, _write_system_settings
from tests.helpers import create_soldier


@pytest.fixture(autouse=True)
def _clear_system_settings_for_export_tests(admin_session) -> None:
    """Clear system_settings before each test so the export tests work correctly."""
    admin_session.execute(delete(SystemSetting))
    admin_session.commit()


def _rows(ws):
    return [
        [c.value for c in row]
        for row in ws.iter_rows(min_row=2)
        if any(c.value is not None for c in row)
    ]


def test_write_system_settings_writes_key_and_json_value(admin_session):
    admin_session.add(SystemSetting(key="algorithm.max_duties_per_window", value=8, updated_by=None))
    admin_session.add(SystemSetting(key="telegram.enabled", value=True, updated_by=None))
    admin_session.commit()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _write_system_settings(wb, admin_session)

    rows = {r[0]: r[1] for r in _rows(wb["system_settings"])}
    assert rows["algorithm.max_duties_per_window"] == "8"
    assert rows["telegram.enabled"] == "true"


def test_write_system_settings_excludes_hidden_keys(admin_session):
    admin_session.add(SystemSetting(key="system.holding_node_id", value="abc", updated_by=None))
    admin_session.commit()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _write_system_settings(wb, admin_session)

    assert _rows(wb["system_settings"]) == []


def test_write_bug_reports_resolves_reporter_and_serializes_json_columns(admin_session):
    reporter = create_soldier(admin_session, personal_number="5556667", role="soldier")
    admin_session.add(BugReport(
        reporter_id=reporter.id, description="בעיה", severity="high", route="/x", status="open",
        nav_history=[{"path": "/a"}], audit_snapshot=None, user_snapshot={"role": "soldier"},
    ))
    admin_session.commit()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _write_bug_reports(wb, admin_session)

    row = _rows(wb["bug_reports"])[0]
    header = [c.value for c in wb["bug_reports"][1]]
    data = dict(zip(header, row))
    assert data["reporter_personal_number"] == "5556667"
    assert data["description"] == "בעיה"
    assert json.loads(data["nav_history_json"]) == [{"path": "/a"}]
    assert data["audit_snapshot_json"] == ""
    assert json.loads(data["user_snapshot_json"]) == {"role": "soldier"}
