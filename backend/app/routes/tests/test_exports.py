from __future__ import annotations

import io

import openpyxl
import pytest
from sqlalchemy import func, select

from app.db.base import Base
from tests.helpers import auth_headers, create_soldier


def _payload(*, filename: str = "table.xlsx", rows=None):
    return {
        "filename": filename,
        "matrix": {
            "sheet_name": "Table",
            "headers": ["Name", "Value"],
            "rows": rows if rows is not None else [["Ada", 3], ["=1+1", "@name"]],
        },
    }


def test_matrix_export_rejects_anonymous_request_before_reading_oversized_body(
    client, monkeypatch
):
    from app.routes import exports

    monkeypatch.setattr(exports, "MAX_EXPORT_REQUEST_BYTES", 8)
    response = client.post(
        "/api/exports/xlsx",
        content=b"not-json-and-larger-than-the-configured-cap",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_matrix_export_returns_readable_workbook_with_safe_text_and_headers(
    client, admin_session
):
    user = create_soldier(admin_session, personal_number="xlsx_matrix_auth")
    before_row_counts = {
        table.name: admin_session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }

    response = client.post(
        "/api/exports/xlsx", json=_payload(), headers=auth_headers(user)
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"] == 'attachment; filename="table.xlsx"'
    workbook = openpyxl.load_workbook(io.BytesIO(response.content), data_only=False)
    worksheet = workbook["Table"]
    assert [cell.value for cell in worksheet[1]] == ["Name", "Value"]
    assert worksheet["A2"].value == "Ada"
    assert worksheet["B2"].value == 3
    assert worksheet["A3"].value == "=1+1"
    assert worksheet["B3"].value == "@name"
    assert worksheet["A3"].data_type == "s"
    assert worksheet["B3"].data_type == "s"
    after_row_counts = {
        table.name: admin_session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }
    assert after_row_counts == before_row_counts


@pytest.mark.parametrize(
    ("filename", "rows"),
    [
        ("../bad.xlsx", [["ok", 1]]),
        ("bad\r\nX-Injected: yes.xlsx", [["ok", 1]]),
        ("table.xlsx", [["ok", {"nested": "value"}]]),
    ],
)
def test_matrix_export_rejects_invalid_filename_or_strict_cell(
    client, admin_session, filename, rows
):
    user = create_soldier(
        admin_session, personal_number="xlsx_matrix_invalid"
    )
    response = client.post(
        "/api/exports/xlsx",
        json=_payload(filename=filename, rows=rows),
        headers=auth_headers(user),
    )
    assert response.status_code == 422


def test_matrix_export_enforces_raw_request_size_cap(client, admin_session, monkeypatch):
    from app.routes import exports

    user = create_soldier(admin_session, personal_number="xlsx_matrix_size")
    monkeypatch.setattr(exports, "MAX_EXPORT_REQUEST_BYTES", 32)
    response = client.post(
        "/api/exports/xlsx",
        json=_payload(),
        headers=auth_headers(user),
    )
    assert response.status_code == 413
