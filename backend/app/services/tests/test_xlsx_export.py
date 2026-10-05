from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook
from pydantic import ValidationError

from app.services.xlsx_export import (
    MAX_EXPORT_CELL_TEXT,
    MAX_EXPORT_COLUMNS,
    MAX_EXPORT_ROWS,
    MAX_EXPORT_SHEETS,
    WorksheetMatrix,
    build_matrix_workbook,
    validate_export_filename,
    write_matrix_sheet,
)


def _read_matrix(data: bytes):
    workbook = load_workbook(BytesIO(data), data_only=False)
    worksheet = workbook.active
    return workbook, worksheet


def _matrix(sheet_name: str, headers: list[object], rows: list[list[object]]) -> WorksheetMatrix:
    return WorksheetMatrix(sheet_name=sheet_name, headers=headers, rows=rows)


def test_round_trips_hebrew_headers_and_supported_scalar_cells():
    matrix = WorksheetMatrix(
        sheet_name="דוח",
        headers=["שם", "מספר", "פעיל", "ריק"],
        rows=[["נועה", 4, True, None], ["", 2.5, False, None]],
    )

    workbook, worksheet = _read_matrix(build_matrix_workbook([matrix]))

    assert workbook.sheetnames == ["דוח"]
    assert list(worksheet.values) == [
        ("שם", "מספר", "פעיל", "ריק"),
        ("נועה", 4, True, None),
        (None, 2.5, False, None),
    ]


def test_round_trips_supported_scalar_headers():
    matrix = WorksheetMatrix(
        sheet_name="Typed headers",
        headers=["Name", 7, None, True],
        rows=[["Ada", 8, None, False]],
    )

    workbook, worksheet = _read_matrix(build_matrix_workbook([matrix]))

    assert list(worksheet.values) == [("Name", 7, None, True), ("Ada", 8, None, False)]
    workbook.close()


@pytest.mark.parametrize(
    ("header", "error_type", "message"),
    [
        (float("nan"), ValueError, "finite"),
        (float("inf"), ValueError, "finite"),
        ("bad\x00text", ValueError, "XML"),
        ("x" * (MAX_EXPORT_CELL_TEXT + 1), ValueError, "length"),
        (object(), ValidationError, "Input should be"),
    ],
    ids=["nan", "infinity", "illegal-xml", "too-long", "unsupported"],
)
def test_rejects_invalid_header_cells(header, error_type, message):
    with pytest.raises(error_type, match=message):
        matrix = WorksheetMatrix(sheet_name="Data", headers=[header], rows=[])
        build_matrix_workbook([matrix])


def test_accepts_a_worksheet_with_no_data_rows():
    workbook, worksheet = _read_matrix(build_matrix_workbook([_matrix("Empty", ["header"], [])]))

    assert workbook.sheetnames == ["Empty"]
    assert list(worksheet.values) == [("header",)]
    workbook.close()


@pytest.mark.parametrize("value", ["=1+1", "+SUM(A1)", "-1", "@name"])
def test_formula_like_strings_are_stored_as_text(value: str):
    workbook, worksheet = _read_matrix(
        build_matrix_workbook([_matrix("Data", ["value"], [[value]])])
    )

    cell = worksheet["A2"]
    assert cell.value == value
    assert cell.data_type == "s"
    workbook.close()


@pytest.mark.parametrize(
    "title",
    [
        "",
        "a" * 32,
        "bad/name",
        "bad\\name",
        "bad:name",
        "bad?name",
        "bad*name",
        "bad[name",
        "bad]name",
        "'edge",
        "edge'",
    ],
)
def test_rejects_invalid_worksheet_titles(title: str):
    with pytest.raises(ValueError):
        build_matrix_workbook([_matrix(title, ["h"], [])])


def test_rejects_duplicate_worksheet_titles():
    matrices = [_matrix("Data", ["a"], []), _matrix("Data", ["b"], [])]

    with pytest.raises(ValueError, match="unique"):
        build_matrix_workbook(matrices)

    case_variant_titles = [_matrix("Data", ["a"], []), _matrix("data", ["b"], [])]
    with pytest.raises(ValueError, match="unique"):
        build_matrix_workbook(case_variant_titles)


def test_rejects_empty_or_excessive_worksheet_lists():
    with pytest.raises(ValueError, match="At least one"):
        build_matrix_workbook([])
    matrices = [_matrix(f"Sheet{i}", ["h"], []) for i in range(MAX_EXPORT_SHEETS + 1)]

    with pytest.raises(ValueError, match="Worksheet count"):
        build_matrix_workbook(matrices)


def test_rejects_ragged_rows():
    matrix = _matrix("Data", ["a", "b"], [[1]])

    with pytest.raises(ValueError, match="width"):
        build_matrix_workbook([matrix])


@pytest.mark.parametrize("value", ["bad\x00text", "bad\x01text", "bad\ud800text"])
def test_rejects_illegal_xml_characters(value: str):
    matrix = _matrix("Data", ["value"], [[value]])

    with pytest.raises(ValueError, match="XML"):
        build_matrix_workbook([matrix])


def test_rejects_cell_text_longer_than_excel_limit():
    matrix = _matrix("Data", ["value"], [["x" * (MAX_EXPORT_CELL_TEXT + 1)]])

    with pytest.raises(ValueError, match="length"):
        build_matrix_workbook([matrix])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_numbers(value: float):
    with pytest.raises(ValueError, match="finite"):
        build_matrix_workbook([_matrix("Data", ["value"], [[value]])])


def test_numeric_looking_string_remains_a_string_cell():
    workbook, worksheet = _read_matrix(
        build_matrix_workbook([_matrix("Data", ["value"], [["12"]])])
    )

    assert worksheet["A2"].value == "12"
    assert worksheet["A2"].data_type == "s"
    workbook.close()


def test_rejects_non_string_headers_and_unsupported_cells():
    with pytest.raises(ValidationError):
        _matrix("Data", ["value"], [[object()]])


def test_rejects_row_limit_plus_one():
    matrix = _matrix("Data", ["v"], [[None]] * (MAX_EXPORT_ROWS + 1))

    with pytest.raises(ValueError, match="row limit"):
        build_matrix_workbook([matrix])


def test_row_limit_applies_per_sheet_when_workbook_total_exceeds_limit():
    matrices = [
        _matrix("First", ["v"], [[0] for _ in range(13_000)]),
        _matrix("Second", ["v"], [[0] for _ in range(13_000)]),
    ]

    workbook, _ = _read_matrix(build_matrix_workbook(matrices))

    assert workbook.sheetnames == ["First", "Second"]
    assert workbook["First"].max_row == 13_001
    assert workbook["Second"].max_row == 13_001
    workbook.close()


def test_rejects_column_limit_plus_one():
    matrix = _matrix("Data", ["h"] * (MAX_EXPORT_COLUMNS + 1), [])

    with pytest.raises(ValueError, match="column limit"):
        build_matrix_workbook([matrix])


def test_rejects_aggregate_cell_limit_plus_one():
    # Each sheet stays within the row and column caps; the combined headers
    # and values exceed the workbook-wide cell budget by one.
    matrices = [
        _matrix("First", ["h"] * 250, [[None] * 250 for _ in range(1999)]),
        _matrix("Second", ["h"], []),
    ]

    with pytest.raises(ValueError, match="cell limit"):
        build_matrix_workbook(matrices)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        ".xlsx",
        " .xlsx",
        "../report.xlsx",
        "folder\\report.xlsx",
        "bad\nname.xlsx",
        "report.csv",
        "report.xlsx.exe",
    ],
)
def test_rejects_unsafe_or_non_xlsx_filenames(filename: str):
    with pytest.raises(ValueError):
        validate_export_filename(filename)


@pytest.mark.parametrize("filename", ["report.xlsx", "weekly report_2.xlsx", "דוח.xlsx"])
def test_returns_safe_ascii_xlsx_filename(filename: str):
    result = validate_export_filename(filename)

    assert result.isascii()
    assert result.endswith(".xlsx")
    assert all(character.isalnum() or character in "._- " for character in result)


def test_write_matrix_sheet_rejects_case_insensitive_collision():
    workbook = Workbook()
    workbook.active.title = "Existing"

    with pytest.raises(ValueError, match="unique"):
        write_matrix_sheet(workbook, _matrix("existing", ["h"], []))

    assert workbook.sheetnames == ["Existing"]
    workbook.close()
