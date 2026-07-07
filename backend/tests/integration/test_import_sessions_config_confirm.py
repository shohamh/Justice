from __future__ import annotations

import io
import uuid
from decimal import Decimal

import openpyxl

import app.services.import_parsers.v1_standard  # noqa: F401
from app.db.models import (
    DutyManagerScope,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
)
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


def test_confirm_creates_hierarchy_node_with_commander_and_duty_manager(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}")
    node_name = f"מדור_{_uid()}"

    xlsx = _wb({
        "hierarchy": [
            ["name", "level", "parent_name", "commander_personal_number", "commander_name", "duty_managers"],
            [node_name, "group", "", commander.personal_number, "", f"{dm.personal_number}:{dm.full_name}"],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["created"] == 1

    node = admin_session.query(HierarchyNode).filter_by(name=node_name).one()
    assert node.commander_id == commander.id
    scope = admin_session.query(DutyManagerScope).filter_by(hierarchy_node_id=node.id).one()
    assert scope.duty_manager_id == dm.id

    # Regression guard: assigning a commander to a brand-new node on import
    # must go through the same set_commander() side effects as an update
    # would — the commander's hierarchy_node_id and display role must be
    # updated too, not just the node's commander_id column.
    admin_session.refresh(commander)
    assert commander.hierarchy_node_id == node.id
    assert commander.role == "commander"


def test_confirm_creates_exemption_type_with_applies_to(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.commit()
    et_name = f"פטור_{_uid()}"

    xlsx = _wb({
        "exemption_types": [
            ["name", "description", "is_global", "is_medical", "is_commander_exemption", "applies_to_duty_types"],
            [et_name, "", "false", "true", "false", dt.name],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["created"] == 1

    et = admin_session.query(ExemptionType).filter_by(name=et_name).one()
    m = admin_session.query(ExemptionDutyTypeMap).filter_by(exemption_type_id=et.id).one()
    assert m.duty_type_id == dt.id


def test_confirm_links_forward_referenced_parent_in_same_sheet(client, admin_session):
    # Regression guard for the two-sub-pass hierarchy commit logic: a child row
    # appears *before* its parent row in the sheet, so at resolve time the
    # parent has no id yet (resolved_parent_id is None, only parent_name is
    # set). The second commit sub-pass must still link them via move_node
    # after both rows have been created.
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    parent_name = f"אגד_{_uid()}"
    child_name = f"מדור_{_uid()}"

    xlsx = _wb({
        "hierarchy": [
            ["name", "level", "parent_name", "commander_personal_number", "commander_name", "duty_managers"],
            [child_name, "group", parent_name, "", "", ""],
            [parent_name, "branch", "", "", "", ""],
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
    assert confirmed.json()["errors"] == []

    parent = admin_session.query(HierarchyNode).filter_by(name=parent_name).one()
    child = admin_session.query(HierarchyNode).filter_by(name=child_name).one()
    assert child.parent_id == parent.id
