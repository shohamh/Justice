from __future__ import annotations

from app.db.models import DutyLocation
from app.services.import_parsers.schema import ImportDutyLocationRow, ParsedImportData
from app.services.import_sessions import _resolve_duty_locations


def test_resolve_duty_locations_new_and_update(app_session):
    existing = DutyLocation(name="שער קיים", base="בסיס א")
    app_session.add(existing)
    app_session.flush()

    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[
            ImportDutyLocationRow(source_row=2, name="שער קיים", base="בסיס ב", active=True),
            ImportDutyLocationRow(source_row=3, name="שער חדש", base=None, active=None),
        ],
    )
    result = _resolve_duty_locations(app_session, data)
    assert result[0]["action"] == "update"
    assert result[0]["existing_id"] == str(existing.id)
    assert result[1]["action"] == "new"
    assert result[1]["existing_id"] is None


def test_resolve_duty_locations_missing_name_error(app_session):
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[
            ImportDutyLocationRow(source_row=2, name="", base="בסיס א", active=True),
        ],
    )
    result = _resolve_duty_locations(app_session, data)
    assert result[0]["action"] == "error"
    assert "חסר שם מיקום" in result[0]["errors"]
    assert result[0]["existing_id"] is None


def test_resolve_duty_locations_preserves_fields(app_session):
    """Verify that all fields from ImportDutyLocationRow are preserved in output."""
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[
            ImportDutyLocationRow(source_row=5, name="שער נוסף", base="בסיס ג", active=False),
        ],
    )
    result = _resolve_duty_locations(app_session, data)
    row = result[0]

    assert row["row"] == 5
    assert row["name"] == "שער נוסף"
    assert row["base"] == "בסיס ג"
    assert row["active"] is False
    assert row["action"] == "new"
    assert row["errors"] == []
    assert row["existing_id"] is None


def test_resolve_duty_locations_empty_sheet(app_session):
    """Verify handling of empty duty_locations list."""
    data = ParsedImportData(
        parser_id="v1_standard",
        duty_locations=[],
    )
    result = _resolve_duty_locations(app_session, data)
    assert result == []
