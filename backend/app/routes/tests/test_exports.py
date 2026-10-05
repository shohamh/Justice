from __future__ import annotations

import io

import openpyxl
import pytest
from sqlalchemy import func, select

from app.db.base import Base
from tests.helpers import auth_headers, create_soldier


def _planning_payload(**overrides):
    payload = {
        "filename": "planning.xlsx",
        "tables": [
            {
                "sheet_name": "transparency",
                "headers": ["Name", "Value"],
                "rows": [["Ada", "=1+1"]],
            }
        ],
        "config_sheets": ["range_locations"],
        "data_sheets": ["rank_advancement_intervals"],
    }
    payload.update(overrides)
    return payload



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


def test_planning_export_combines_client_and_server_sheets_in_order(client, admin_session):
    from app.db.base import Base

    admin = create_soldier(admin_session, personal_number="planning_export_admin", role="admin")
    admin_session.commit()
    before_counts = {
        table.name: admin_session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }

    response = client.post(
        "/api/exports/planning-xlsx",
        json=_planning_payload(),
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="planning.xlsx"'
    workbook = openpyxl.load_workbook(io.BytesIO(response.content), data_only=False)
    assert workbook.sheetnames == [
        "transparency",
        "מיקומי מטווח",
        "מועדי קידום",
    ]
    assert [cell.value for cell in workbook["transparency"][1]] == ["Name", "Value"]
    assert workbook["transparency"]["A2"].value == "Ada"
    assert workbook["transparency"]["B2"].value == "=1+1"
    assert workbook["transparency"]["B2"].data_type == "s"
    from app.services.excel_bilingual import HE_HEADERS

    assert [cell.value for cell in workbook["מיקומי מטווח"][1]] == [
        HE_HEADERS["name"],
        HE_HEADERS["active"],
    ]
    assert [cell.value for cell in workbook["מועדי קידום"][1]] == [
        HE_HEADERS["track"],
        HE_HEADERS["rank"],
        HE_HEADERS["months_to_next"],
        HE_HEADERS["advance_on_career_entry"],
    ]
    after_counts = {
        table.name: admin_session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }
    assert after_counts == before_counts


@pytest.mark.parametrize(
    "payload",
    [
        _planning_payload(config_sheets=["not_a_config_sheet"]),
        _planning_payload(data_sheets=["not_a_data_sheet"]),
        _planning_payload(tables=[{"sheet_name": "soldiers", "headers": ["x"], "rows": []}]),
    ],
)
def test_planning_export_rejects_unknown_sheet_keys(client, admin_session, payload):
    admin = create_soldier(admin_session, personal_number="planning_export_invalid", role="admin")
    admin_session.commit()

    response = client.post("/api/exports/planning-xlsx", json=payload, headers=auth_headers(admin))

    assert response.status_code == 422


def test_planning_export_rejects_empty_selection(client, admin_session):
    admin = create_soldier(admin_session, personal_number="planning_export_empty", role="admin")
    admin_session.commit()

    response = client.post(
        "/api/exports/planning-xlsx",
        json=_planning_payload(tables=[], config_sheets=[], data_sheets=[]),
        headers=auth_headers(admin),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "no_exportable_sheets"


def test_planning_export_requires_duty_manager_or_admin(client, admin_session):
    anonymous = client.post("/api/exports/planning-xlsx", json=_planning_payload())
    soldier = create_soldier(admin_session, personal_number="planning_export_soldier")
    admin_session.commit()

    forbidden = client.post(
        "/api/exports/planning-xlsx",
        json=_planning_payload(),
        headers=auth_headers(soldier),
    )

    assert anonymous.status_code == 401
    assert forbidden.status_code == 403


def test_planning_export_duty_manager_omits_admin_only_config_sheets(client, admin_session):
    from app.db.models import DutyManagerScope
    from app.services.hierarchy import create_node

    dm = create_soldier(admin_session, personal_number="planning_export_dm", role="duty_manager")
    node = create_node(admin_session, level="team", name="planning_export_node", parent_id=None)
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()
    payload = _planning_payload(
        tables=[],
        config_sheets=["system_settings", "range_locations", "bug_reports"],
        data_sheets=[],
    )

    response = client.post("/api/exports/planning-xlsx", json=payload, headers=auth_headers(dm))

    assert response.status_code == 200
    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["מיקומי מטווח"]


def test_planning_export_enforces_aggregate_client_cell_budget(client, admin_session, monkeypatch):
    from app.routes import exports

    admin = create_soldier(admin_session, personal_number="planning_export_cells", role="admin")
    admin_session.commit()
    monkeypatch.setattr(exports, "MAX_EXPORT_CELLS", 3)
    matrices = [
        {"sheet_name": name, "headers": ["a", "b"], "rows": []}
        for name in ("transparency", "sub_units")
    ]

    response = client.post(
        "/api/exports/planning-xlsx",
        json=_planning_payload(tables=matrices, config_sheets=[], data_sheets=[]),
        headers=auth_headers(admin),
    )

    assert response.status_code == 422


def test_planning_export_enforces_raw_request_size_cap(client, admin_session, monkeypatch):
    from app.routes import exports

    admin = create_soldier(admin_session, personal_number="planning_export_size", role="admin")
    admin_session.commit()
    monkeypatch.setattr(exports, "MAX_EXPORT_REQUEST_BYTES", 32)

    response = client.post(
        "/api/exports/planning-xlsx",
        json=_planning_payload(),
        headers=auth_headers(admin),
    )

    assert response.status_code == 413
