from __future__ import annotations

import io

import openpyxl

from tests.helpers import auth_headers, create_soldier


def test_template_includes_all_six_sheets(client, admin_session):
    admin = create_soldier(admin_session, personal_number="tmpl-admin", role="admin")
    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/template", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) >= {
        "soldiers", "duty_shifts", "duty_locations", "hierarchy", "duty_types", "exemption_types",
    }


def test_template_includes_range_sheets(client, admin_session):
    admin = create_soldier(admin_session, personal_number="tmpl-admin-range", role="admin")
    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/template", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    for name in (
        "range_locations", "range_events", "range_assignments",
        "soldier_range_qualifications", "range_excusal_requests",
    ):
        assert name in wb.sheetnames
