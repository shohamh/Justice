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
