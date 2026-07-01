from __future__ import annotations

import io
import uuid
from decimal import Decimal

import openpyxl
import pytest

from app.db.models import DutyManagerScope, DutyLocation
from app.services.duty_config import create_duty_type
import app.services.import_parsers.v1_standard  # noqa: F401  (registers "v1_standard" parser)
from app.services.import_sessions import ImportSessionError, create_session, reparse_session
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _wb_with_duty_shifts(rows):
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


def _wb_with_soldiers(rows):
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


def _to_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_create_session_admin_resolvable_duty_shift(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )

    assert sess.status == "draft"
    row = sess.parsed_state["duty_shifts"][0]
    assert row["action"] == "new"
    assert row["resolved_duty_type_id"] == str(dt.id)
    assert row["resolved_duty_location_id"] == str(loc.id)


def test_create_session_dm_out_of_scope_quota_node(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()

    in_scope_node = create_node(admin_session, level="branch", name=f"in_{_uid()}")
    out_of_scope_node = create_node(admin_session, level="branch", name=f"out_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=in_scope_node.id))
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5,
         f"{out_of_scope_node.name}:2", ""],
    ])

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=dm, parser_id="v1_standard",
    )

    row = sess.parsed_state["duty_shifts"][0]
    assert row["action"] == "out_of_scope"


def test_create_session_unresolved_duty_type_errors(admin_session):
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        ["no_such_duty_type", loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )

    row = sess.parsed_state["duty_shifts"][0]
    assert row["action"] == "error"
    assert any("duty_type" in e for e in row["errors"])


def test_create_session_soldier_unresolved_hierarchy_node_errors(admin_session):
    wb = _wb_with_soldiers([
        ["1234567", "Some Soldier", "", "", "", "no_such_node", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )

    row = sess.parsed_state["soldiers"][0]
    assert row["action"] == "error"
    assert any("hierarchy_node" in e for e in row["errors"])


def test_reparse_session_flips_error_to_new_after_duty_type_created(admin_session):
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    admin_session.commit()

    dt_name = f"dt_{_uid()}"
    wb = _wb_with_duty_shifts([
        [dt_name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()
    assert sess.parsed_state["duty_shifts"][0]["action"] == "error"

    create_duty_type(admin_session, name=dt_name, score_per_day=Decimal("1.00"))
    admin_session.commit()

    reparsed = reparse_session(admin_session, session_id=sess.id, actor=admin)
    assert reparsed.parsed_state["duty_shifts"][0]["action"] == "new"


def test_reparse_session_non_draft_raises(admin_session):
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    sess.status = "confirmed"
    admin_session.commit()

    with pytest.raises(ImportSessionError, match="only draft sessions"):
        reparse_session(admin_session, session_id=sess.id, actor=admin)


def test_reparse_session_not_found_raises(admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    with pytest.raises(ImportSessionError, match="not found"):
        reparse_session(admin_session, session_id=uuid.uuid4(), actor=admin)
