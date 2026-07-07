from __future__ import annotations

import io
import uuid
from decimal import Decimal

import openpyxl

import app.services.import_parsers.v1_standard  # noqa: F401
from app.db.models import DutyLocation, DutyType
from app.services.duty_config import create_duty_type
from tests.helpers import auth_headers, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _token(soldier) -> str:
    return auth_headers(soldier)["Authorization"].split(" ", 1)[1]


def _wb(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, token, xlsx: bytes):
    return client.post(
        "/api/import/sessions?parser_id=v1_standard",
        files={"file": ("import.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_confirm_creates_duty_location_and_duty_type(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    name = f"שמירה_{_uid()}"
    loc_name = f"שער_{_uid()}"
    xlsx = _wb({
        "duty_locations": [["name", "base", "active"], [loc_name, "בסיס א", "true"]],
        "duty_types": [
            ["name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
             "is_external", "contact_name", "contact_phone", "start_time", "end_time",
             "instructions", "eligible_units", "requirements_json"],
            [name, "1.50", "", "true", "0.000", "0", "false", "", "", "", "", "", "", ""],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["created"] == 2
    assert body["errors"] == []

    assert admin_session.query(DutyLocation).filter_by(name=loc_name).one()
    dt = admin_session.query(DutyType).filter_by(name=name).one()
    assert dt.score_per_day == Decimal("1.50")


def test_confirm_updates_existing_duty_location(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    loc = DutyLocation(name=f"שער_{_uid()}", base="ישן")
    admin_session.add(loc)
    admin_session.commit()

    xlsx = _wb({"duty_locations": [["name", "base", "active"], [loc.name, "חדש", "true"]]})
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["updated"] == 1
    admin_session.refresh(loc)
    assert loc.base == "חדש"


def test_confirm_preserves_active_false_and_reserve_minimum_zero(client, admin_session):
    # Regression guard: this feature has repeatedly lost legitimate
    # False/0 values to bare-truthiness bugs in sibling tasks. active=False,
    # reserve_minimum=0, is_external=False must all survive the commit step
    # rather than being silently skipped or defaulted back to True/None.
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    loc_name = f"שער_{_uid()}"
    dt_name = f"dt_{_uid()}"
    xlsx = _wb({
        "duty_locations": [["name", "base", "active"], [loc_name, "בסיס א", "false"]],
        "duty_types": [
            ["name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
             "is_external", "contact_name", "contact_phone", "start_time", "end_time",
             "instructions", "eligible_units", "requirements_json"],
            [dt_name, "1.50", "", "false", "0.000", 0, "false", "", "", "", "", "", "", ""],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["created"] == 2

    loc = admin_session.query(DutyLocation).filter_by(name=loc_name).one()
    assert loc.active is False

    dt = admin_session.query(DutyType).filter_by(name=dt_name).one()
    assert dt.active is False
    assert dt.reserve_minimum == 0
    assert dt.is_external is False
