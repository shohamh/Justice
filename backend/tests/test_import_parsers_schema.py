from __future__ import annotations

from app.services.import_parsers.schema import ParsedImportData


def test_parsed_import_data_defaults_new_sheets_to_empty_lists():
    data = ParsedImportData(parser_id="v1_standard")
    assert data.duty_locations == []
    assert data.hierarchy == []
    assert data.duty_types == []
    assert data.exemption_types == []
