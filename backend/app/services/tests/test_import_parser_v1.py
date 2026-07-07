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


def _wb_with_assignments_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("assignments")
    ws.append([
        "personal_number", "full_name", "duty_type_name", "duty_location_name",
        "start_date", "end_date", "start_time", "end_time", "is_reserve", "notes",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_assignments_sheet_row():
    wb = _wb_with_assignments_sheet([
        ["12345", "ישראל ישראלי", "שמירה", "שער ראשי",
         "15.06.2024", "16.06.2024", "20:00", "06:00", "true", "הערה"],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.assignments) == 1
    row = data.assignments[0]
    assert row.personal_number == "12345"
    assert row.full_name == "ישראל ישראלי"
    assert row.duty_type_name == "שמירה"
    assert row.duty_location_name == "שער ראשי"
    assert row.start_date == "2024-06-15"
    assert row.end_date == "2024-06-16"
    assert row.start_time == "20:00"
    assert row.end_time == "06:00"
    assert row.is_reserve is True
    assert row.notes == "הערה"


def test_assignments_sheet_does_not_produce_synthetic_duty_shifts():
    wb = _wb_with_assignments_sheet([
        ["12345", "ישראל ישראלי", "שמירה", "שער ראשי",
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_shifts == []
    assert not any("assignments" in w for w in data.parser_warnings)


def test_assignments_sheet_absent_gives_empty_list():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    data = V1StandardParser().parse(wb)
    assert data.assignments == []


def test_assignments_and_duty_shifts_both_present_both_parsed():
    wb = _wb_with_assignments_sheet([
        ["12345", "ישראל ישראלי", "שמירה", "שער ראשי",
         "15.06.2024", "16.06.2024", "", "", "false", ""],
    ])
    ws = wb.create_sheet("duty_shifts")
    ws.append([
        "duty_type_name", "duty_location_name", "start_date", "end_date",
        "start_time", "end_time", "required_count", "node_quotas", "notes",
    ])
    ws.append(["שמירה", "שער ראשי", "15.06.2024", "16.06.2024", "", "", 2, "", ""])

    data = V1StandardParser().parse(wb)
    assert len(data.assignments) == 1
    assert len(data.duty_shifts) == 1


def _wb_with_duty_types_sheet(rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("duty_types")
    ws.append([
        "name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
        "is_external", "contact_name", "contact_phone", "start_time", "end_time", "instructions",
        "eligible_unit_names", "requirements_json",
    ])
    for r in rows:
        ws.append(r)
    return wb


def test_parses_duty_types_sheet():
    wb = _wb_with_duty_types_sheet([
        ["שמירה", "1.50", "guard duty", True, "0.30", 5, False, "עמית", "0500000000", "08:00", "16:00", "be alert", "יחידה א,יחידה ב", '{"skill":"shooting"}'],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.duty_types) == 1
    row = data.duty_types[0]
    assert row.name == "שמירה"
    assert row.score_per_day == "1.50"
    assert row.description == "guard duty"
    assert row.active is True
    assert row.reserve_ratio == "0.30"
    assert row.reserve_minimum == 5
    assert row.is_external is False
    assert row.contact_name == "עמית"
    assert row.contact_phone == "0500000000"
    assert row.start_time == "08:00"
    assert row.end_time == "16:00"
    assert row.instructions == "be alert"
    assert row.eligible_unit_names == ["יחידה א", "יחידה ב"]
    assert row.requirements_json == '{"skill":"shooting"}'


def test_duty_types_sheet_absent_gives_empty_list():
    wb = _wb_with_duty_shifts_sheet([
        ["שמירה", "בסיס א", "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert data.duty_types == []


def test_parses_duty_types_with_optional_fields_none():
    wb = _wb_with_duty_types_sheet([
        ["טיול", "2.00", None, None, None, None, None, None, None, None, None, None, None, None],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.duty_types) == 1
    row = data.duty_types[0]
    assert row.name == "טיול"
    assert row.score_per_day == "2.00"
    assert row.description is None
    assert row.active is None
    assert row.reserve_ratio is None
    assert row.reserve_minimum is None
    assert row.is_external is None
    assert row.contact_name is None
    assert row.contact_phone is None
    assert row.start_time is None
    assert row.end_time is None
    assert row.instructions is None
    assert row.eligible_unit_names == []
    assert row.requirements_json is None


def test_parses_duty_types_with_whitespace_in_eligible_units():
    wb = _wb_with_duty_types_sheet([
        ["שמירה", "1.50", "", False, "", 0, False, "", "", "", "", "", "יחידה א , יחידה ב , יחידה ג", ""],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.duty_types) == 1
    row = data.duty_types[0]
    assert row.eligible_unit_names == ["יחידה א", "יחידה ב", "יחידה ג"]


def test_parses_multiple_duty_types():
    wb = _wb_with_duty_types_sheet([
        ["שמירה", "1.50", "guard", True, "0.30", 5, False, "עמית", "0500000000", "", "", "", "יחידה א", ""],
        ["טיול", "2.00", "tour", False, None, None, True, "", "", "10:00", "18:00", "fun", "", '{"skill":"navigation"}'],
    ])
    data = V1StandardParser().parse(wb)
    assert len(data.duty_types) == 2
    assert data.duty_types[0].name == "שמירה"
    assert data.duty_types[1].name == "טיול"
