import openpyxl

from app.services.import_parsers.v1_standard import V1StandardParser


def _wb_with_duty_shifts_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_shifts")
    ws.append([
        "duty_type_name", "duty_location_name", "start_date", "end_date",
        "start_time", "end_time", "required_count", "node_quotas", "notes",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_duty_shifts_with_node_quotas():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 5,
         "ענף פוקוס:2;ענף אלומות:3", ""],
    ])
    parser = V1StandardParser()
    data = parser.parse(wb)
    assert len(data.duty_shifts) == 1
    row = data.duty_shifts[0]
    assert row.duty_type_name == "שמירה"
    assert row.required_count == 5
    assert {(q.node_name, q.count) for q in row.node_quotas} == {
        ("ענף פוקוס", 2), ("ענף אלומות", 3),
    }


def test_parses_duty_shifts_without_node_quotas():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3, "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_shifts[0].node_quotas == []


def test_node_quotas_missing_colon_is_skipped_with_warning():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3, "badformat", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_shifts[0].node_quotas == []
    assert any("badformat" in w for w in data.parser_warnings)


def test_node_quotas_non_integer_count_is_skipped_with_warning():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3, "node:notanumber", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_shifts[0].node_quotas == []
    assert any("node:notanumber" in w for w in data.parser_warnings)


def test_node_quotas_mix_of_valid_and_invalid_entries():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 3,
         "ענף פוקוס:2;badformat;node:notanumber", ""],
    ])
    data = V1StandardParser().parse(wb)
    row = data.duty_shifts[0]
    assert {(q.node_name, q.count) for q in row.node_quotas} == {("ענף פוקוס", 2)}
    assert any("badformat" in w for w in data.parser_warnings)
    assert any("node:notanumber" in w for w in data.parser_warnings)


def test_detect_scores_high_for_known_sheet_names():
    wb = _wb_with_duty_shifts_sheet([])
    score = V1StandardParser().detect(wb)
    assert score >= 0.5


def test_detect_scores_low_for_unrelated_workbook():
    wb = openpyxl.Workbook()
    wb.active.title = "random_sheet"
    score = V1StandardParser().detect(wb)
    assert score < 0.5


def _wb_with_soldiers_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("soldiers")
    ws.append([
        "personal_number", "full_name", "rank", "gender", "is_officer",
        "hierarchy_node_name", "enrolled_at", "enlistment_date", "phone", "email",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_soldiers_sheet_row():
    wb = _wb_with_soldiers_sheet([
        ["12345", "ישראל ישראלי", "רב", "m", "false", "מדור א",
         "01.01.2022", "01.03.2020", "0500000000", "a@b.com"],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.soldiers) == 1
    row = data.soldiers[0]
    assert row.personal_number == "12345"
    assert row.full_name == "ישראל ישראלי"
    assert row.is_officer is False
    assert row.hierarchy_node_name == "מדור א"
    assert row.enrolled_at == "2022-01-01"
    assert row.enlistment_date == "2020-03-01"


def test_soldiers_sheet_absent_gives_empty_list():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    wb.create_sheet("duty_shifts").append([
        "duty_type_name", "duty_location_name", "start_date", "end_date",
        "start_time", "end_time", "required_count", "node_quotas", "notes",
    ])
    data = V1StandardParser().parse(wb)
    assert data.soldiers == []


def test_legacy_assignments_sheet_falls_back_to_duty_shifts():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("assignments")
    ws.append(["personal_number", "duty_type_name", "start_date", "end_date", "is_reserve"])
    ws.append(["12345", "שמירה", "15.06.2024", "16.06.2024", "false"])

    data = V1StandardParser().parse(wb)
    assert len(data.duty_shifts) == 1
    row = data.duty_shifts[0]
    assert row.duty_type_name == "שמירה"
    assert row.start_date == "2024-06-15"
    assert row.end_date == "2024-06-16"
    assert row.required_count == 1
    assert any("assignments" in w for w in data.parser_warnings)


def _wb_with_hierarchy_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("hierarchy")
    ws.append([
        "name", "level", "parent_name", "commander_personal_number", "commander_name", "duty_managers",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_hierarchy_sheet_with_duty_managers():
    wb = _wb_with_hierarchy_sheet([
        ["מדור א", "group", "יחידה ראשית", "12345", "ישראל ישראלי", "12345:ישראל ישראלי;23456:משה כהן"],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.hierarchy) == 1
    row = data.hierarchy[0]
    assert row.name == "מדור א"
    assert row.level == "group"
    assert row.parent_name == "יחידה ראשית"
    assert row.commander_personal_number == "12345"
    assert row.commander_name == "ישראל ישראלי"
    assert row.duty_manager_refs == ["12345:ישראל ישראלי", "23456:משה כהן"]


def test_hierarchy_malformed_duty_manager_entry_produces_warning_not_error():
    wb = _wb_with_hierarchy_sheet([
        ["מדור ב", "group", "", "", "", "not-a-valid-entry"],
    ])
    data = V1StandardParser().parse(wb)
    assert data.hierarchy[0].duty_manager_refs == []
    assert any("מדור ב" in w or "שורה 2" in w for w in data.parser_warnings)


def _wb_with_duty_locations_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_locations")
    ws.append(["name", "base", "active"])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_duty_locations_sheet():
    wb = _wb_with_duty_locations_sheet([
        ["בסיס א", "base_a", True],
        ["בסיס ב", "base_b", False],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.duty_locations) == 2
    assert data.duty_locations[0].name == "בסיס א"
    assert data.duty_locations[0].base == "base_a"
    assert data.duty_locations[0].active is True
    assert data.duty_locations[1].name == "בסיס ב"
    assert data.duty_locations[1].active is False


def test_duty_locations_sheet_absent_gives_empty_list():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_locations == []


def test_parses_duty_locations_with_optional_fields():
    wb = _wb_with_duty_locations_sheet([
        ["בסיס א", None, None],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.duty_locations) == 1
    row = data.duty_locations[0]
    assert row.name == "בסיס א"
    assert row.base is None
    assert row.active is None


def _wb_with_exemption_types_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("exemption_types")
    ws.append(["name", "description", "is_global", "is_medical", "is_commander_exemption", "applies_to_duty_types"])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_exemption_types_sheet():
    wb = _wb_with_exemption_types_sheet([
        ["פטור בריאות", "health reason", True, True, False, ""],
        ["פטור שמירות", "security reason", False, False, False, "שמירה,טיול"],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.exemption_types) == 2
    assert data.exemption_types[0].name == "פטור בריאות"
    assert data.exemption_types[0].is_global is True
    assert data.exemption_types[0].is_medical is True
    assert data.exemption_types[0].applies_to_duty_type_names == []
    assert data.exemption_types[1].name == "פטור שמירות"
    assert data.exemption_types[1].applies_to_duty_type_names == ["שמירה", "טיול"]


def test_exemption_types_sheet_absent_gives_empty_list():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.exemption_types == []


def test_parses_exemption_types_with_whitespace_in_applies_to_list():
    wb = _wb_with_exemption_types_sheet([
        ["פטור שמירות", "", False, False, False, "שמירה , טיול , ביקור"],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.exemption_types) == 1
    row = data.exemption_types[0]
    assert row.applies_to_duty_type_names == ["שמירה", "טיול", "ביקור"]


def _wb_with_duty_types_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_types")
    ws.append([
        "name", "score_per_day", "description", "active", "reserve_ratio",
        "reserve_minimum", "is_external", "contact_name", "contact_phone",
        "start_time", "end_time", "instructions", "eligible_units", "requirements_json",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_duty_types_sheet():
    wb = _wb_with_duty_types_sheet([
        [
            "שמירה", "1.50", "תיאור", "true", "0.200",
            "2", "false", "דני", "050-1234567",
            "20:00", "06:00", "הצטיידות", "מדור א, מדור ב", '{"min_rank": 1}',
        ],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.duty_types) == 1
    row = data.duty_types[0]
    assert row.name == "שמירה"
    assert row.score_per_day == "1.50"
    assert row.description == "תיאור"
    assert row.active is True
    assert row.reserve_ratio == "0.200"
    assert row.reserve_minimum == 2
    assert row.is_external is False
    assert row.contact_name == "דני"
    assert row.contact_phone == "050-1234567"
    assert row.start_time == "20:00"
    assert row.end_time == "06:00"
    assert row.instructions == "הצטיידות"
    # Regression test: the spreadsheet column is `eligible_units`, not
    # `eligible_unit_names` — the parser must read from the real column name.
    assert row.eligible_unit_names == ["מדור א", "מדור ב"]
    assert row.requirements_json == '{"min_rank": 1}'


def test_duty_types_numeric_fields_stay_as_raw_strings_or_ints():
    wb = _wb_with_duty_types_sheet([
        [
            "שמירה", "1.50", "", "", "0.200",
            "2", "", "", "",
            "", "", "", "", "",
        ],
    ])
    data = V1StandardParser().parse(wb)
    row = data.duty_types[0]
    # score_per_day and reserve_ratio are kept as raw strings (not Decimal)
    # at this parsing stage — conversion happens later in validation.
    assert row.score_per_day == "1.50"
    assert isinstance(row.score_per_day, str)
    assert row.reserve_ratio == "0.200"
    assert isinstance(row.reserve_ratio, str)
    # reserve_minimum is parsed as an int at this stage.
    assert row.reserve_minimum == 2
    assert isinstance(row.reserve_minimum, int)


def test_duty_types_sheet_absent_gives_empty_list():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_types == []
