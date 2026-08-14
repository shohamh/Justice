from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
from dateutil.relativedelta import relativedelta

import app.services.import_parsers.v1_standard  # noqa: F401
from app.db.models import (
    DutyManagerScope,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    Soldier,
)
from app.services.duty_config import create_duty_type
from app.services.rank_advancement import recompute_affected_soldiers, upsert_interval
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


def test_session_summary_includes_new_group_counts(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    xlsx = _wb({"duty_locations": [["name", "base", "active"], [f"שער_{_uid()}", "", "true"]]})
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    listing = client.get(
        "/api/import/sessions", headers={"Authorization": f"Bearer {_token(admin)}"}
    ).json()
    entry = next(s for s in listing if s["id"] == session_id)
    assert entry["row_summary"]["duty_locations"] == 1


def test_confirm_creates_and_updates_duty_type_start_end_time(client, admin_session):
    # Regression guard: start_time/end_time are parsed and resolved but were
    # never passed to create_duty_type()/update_duty_type() in confirm_session(),
    # silently dropping them on both create and update.
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    dt_name = f"dt_{_uid()}"
    xlsx = _wb({
        "duty_types": [
            ["name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
             "is_external", "contact_name", "contact_phone", "start_time", "end_time",
             "instructions", "eligible_units", "requirements_json"],
            [dt_name, "1.50", "", "true", "0.000", "0", "false", "", "", "20:00", "06:00", "", "", ""],
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

    dt = admin_session.query(DutyType).filter_by(name=dt_name).one()
    assert dt.start_time is not None and dt.start_time.strftime("%H:%M") == "20:00"
    assert dt.end_time is not None and dt.end_time.strftime("%H:%M") == "06:00"

    # Update path: change the times via a second import of the same name.
    xlsx2 = _wb({
        "duty_types": [
            ["name", "score_per_day", "description", "active", "reserve_ratio", "reserve_minimum",
             "is_external", "contact_name", "contact_phone", "start_time", "end_time",
             "instructions", "eligible_units", "requirements_json"],
            [dt_name, "1.50", "", "true", "0.000", "0", "false", "", "", "21:00", "07:00", "", "", ""],
        ],
    })
    resp2 = _upload(client, _token(admin), xlsx2)
    confirmed2 = client.post(
        f"/api/import/sessions/{resp2.json()['session_id']}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed2.status_code == 200
    assert confirmed2.json()["updated"] == 1
    admin_session.refresh(dt)
    assert dt.start_time.strftime("%H:%M") == "21:00"
    assert dt.end_time.strftime("%H:%M") == "07:00"


def test_session_row_summary_includes_range_sheets(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    xlsx = _wb({"range_locations": [["name", "active"], ["מטווח חדש", "true"]]})
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]

    listing = client.get(
        "/api/import/sessions", headers={"Authorization": f"Bearer {_token(admin)}"}
    ).json()
    entry = next(s for s in listing if s["id"] == session_id)
    assert entry["row_summary"]["range_locations"] == 1
    assert entry["row_summary"]["range_events"] == 0
    assert entry["row_summary"]["range_assignments"] == 0
    assert entry["row_summary"]["soldier_range_qualifications"] == 0
    assert entry["row_summary"]["range_excusal_requests"] == 0


# ── Task 13: rank-advancement initialization on import ──────────────────────


def test_confirm_new_soldier_with_rank_computes_next_rank_date_from_enlistment(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    upsert_interval(admin_session, track="enlisted", rank="טוראי", months_to_next=8, actor_id=None)
    admin_session.commit()

    pn = f"imp_{_uid()}"
    enlistment = date.today() - timedelta(days=100)
    xlsx = _wb({
        "soldiers": [
            ["personal_number", "full_name", "rank", "enlistment_date"],
            [pn, "חייל בדיקה", "טוראי", enlistment.isoformat()],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]
    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["created"] == 1

    soldier = admin_session.query(Soldier).filter_by(personal_number=pn).one()
    assert soldier.current_rank_since == enlistment
    assert soldier.next_rank_date == enlistment + relativedelta(months=8)
    assert soldier.next_rank_date_overridden is False


def test_confirm_new_soldier_with_explicit_next_rank_date_marks_overridden(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    upsert_interval(admin_session, track="enlisted", rank="טוראי", months_to_next=8, actor_id=None)
    admin_session.commit()

    pn = f"imp_{_uid()}"
    explicit_date = date.today() + timedelta(days=365)
    xlsx = _wb({
        "soldiers": [
            ["personal_number", "full_name", "rank", "next_rank_date"],
            [pn, "חייל בדיקה", "טוראי", explicit_date.isoformat()],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]
    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["created"] == 1

    soldier = admin_session.query(Soldier).filter_by(personal_number=pn).one()
    assert soldier.next_rank_date == explicit_date
    assert soldier.next_rank_date_overridden is True
    # current_rank_since still gets derived — it tracks a separate concern
    # (when the current rank took effect) from whether next_rank_date itself
    # was manually overridden.
    assert soldier.current_rank_since is not None

    # A subsequent config-driven recompute must not clobber the manual override.
    recompute_affected_soldiers(admin_session, track="enlisted", rank="טוראי")
    admin_session.commit()
    admin_session.refresh(soldier)
    assert soldier.next_rank_date == explicit_date


def test_confirm_new_soldier_with_rank_but_no_interval_leaves_next_rank_date_none(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    pn = f"imp_{_uid()}"
    xlsx = _wb({
        "soldiers": [
            ["personal_number", "full_name", "rank"],
            [pn, "חייל בדיקה", "טוראי"],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]
    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200, confirmed.text

    soldier = admin_session.query(Soldier).filter_by(personal_number=pn).one()
    assert soldier.current_rank_since is not None
    assert soldier.next_rank_date is None
    assert soldier.next_rank_date_overridden is False


def test_confirm_new_soldier_without_rank_leaves_rank_advancement_fields_untouched(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    pn = f"imp_{_uid()}"
    xlsx = _wb({
        "soldiers": [
            ["personal_number", "full_name"],
            [pn, "חייל בדיקה"],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]
    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200, confirmed.text

    soldier = admin_session.query(Soldier).filter_by(personal_number=pn).one()
    assert soldier.rank is None
    assert soldier.current_rank_since is None
    assert soldier.next_rank_date is None
    assert soldier.next_rank_date_overridden is False


def test_confirm_updates_existing_soldier_rank_initializes_next_rank_date(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    existing = create_soldier(admin_session, personal_number=f"exist_{_uid()}")
    upsert_interval(admin_session, track="enlisted", rank="רבט", months_to_next=6, actor_id=None)
    admin_session.commit()

    xlsx = _wb({
        "soldiers": [
            ["personal_number", "full_name", "rank"],
            [existing.personal_number, existing.full_name, "רבט"],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]
    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["updated"] == 1

    admin_session.refresh(existing)
    assert existing.rank == "רבט"
    assert existing.current_rank_since == date.today()
    assert existing.next_rank_date == date.today() + relativedelta(months=6)
    assert existing.next_rank_date_overridden is False


def test_confirm_updates_existing_soldier_without_rank_column_leaves_rank_advancement_untouched(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    existing = create_soldier(admin_session, personal_number=f"exist_{_uid()}")
    existing.rank = "טוראי"
    existing.next_rank_date = date(2030, 1, 1)
    existing.current_rank_since = date(2020, 1, 1)
    existing.next_rank_date_overridden = True
    admin_session.commit()

    xlsx = _wb({
        "soldiers": [
            ["personal_number", "full_name"],
            [existing.personal_number, "שם חדש"],
        ],
    })
    resp = _upload(client, _token(admin), xlsx)
    session_id = resp.json()["session_id"]
    confirmed = client.post(
        f"/api/import/sessions/{session_id}/confirm",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["updated"] == 1

    admin_session.refresh(existing)
    assert existing.full_name == "שם חדש"
    assert existing.rank == "טוראי"
    assert existing.next_rank_date == date(2030, 1, 1)
    assert existing.current_rank_since == date(2020, 1, 1)
    assert existing.next_rank_date_overridden is True
