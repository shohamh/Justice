from __future__ import annotations

import io
import uuid
from decimal import Decimal

import openpyxl
import pytest
from sqlalchemy import select

from app.db.models import DutyManagerScope, DutyLocation, DutyShiftNodeQuota, Soldier
from app.services.duty_config import create_duty_type
import app.services.import_parsers.v1_standard  # noqa: F401  (registers "v1_standard" parser)
from app.services.import_sessions import (
    ImportSessionError,
    cancel_session,
    confirm_session,
    create_session,
    mark_done,
    reparse_session,
    set_selections,
)
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
    assert any("no_such_duty_type" in e for e in row["errors"])


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
    assert any("no_such_node" in e for e in row["errors"])


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


def test_set_selections_persists(admin_session):
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
    admin_session.commit()

    selections = {"duty_shifts": {"1": "skip"}}
    updated = set_selections(admin_session, session_id=sess.id, selections=selections)
    assert updated.user_selections == selections

    admin_session.commit()
    admin_session.refresh(sess)
    assert sess.user_selections == selections


def test_confirm_session_mixed_actions(admin_session):
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    admin_session.commit()

    wb = _wb_with_soldiers([
        ["1111111", "New Soldier", "", "", "", "", "", "", "", ""],
        ["2222222", "Skip Soldier", "", "", "", "", "", "", "", ""],
        ["no_such_node_soldier", "Error Soldier", "", "", "", node.name + "_bogus", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()

    rows = sess.parsed_state["soldiers"]
    assert rows[0]["action"] == "new"
    assert rows[1]["action"] == "new"
    assert rows[2]["action"] == "error"

    # User selects "skip" for row 2 (the second row, effective row number = its source_row)
    row2_num = str(rows[1]["row"])
    set_selections(admin_session, session_id=sess.id, selections={"soldiers": {row2_num: "skip"}})
    admin_session.commit()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["created"] == 1
    assert result["skipped"] == 2
    assert result["updated"] == 0

    admin_session.refresh(sess)
    assert sess.status == "confirmed"
    assert sess.confirmed_at is not None
    assert len(sess.created_links["soldiers"]) == 1

    created_id = sess.created_links["soldiers"][0]
    created_soldier = admin_session.get(Soldier, uuid.UUID(created_id))
    assert created_soldier is not None
    assert created_soldier.personal_number == "1111111"


def test_confirm_session_duty_shift_with_node_quota_writes_quota(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, f"{node.name}:3", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["created"] == 1
    assert result["skipped"] == 0

    shift_id = uuid.UUID(sess.created_links["duty_shifts"][0])
    quotas = admin_session.execute(
        select(DutyShiftNodeQuota).where(DutyShiftNodeQuota.duty_shift_id == shift_id)
    ).scalars().all()
    assert len(quotas) == 1
    assert quotas[0].hierarchy_node_id == node.id
    assert quotas[0].count == 3


def test_confirm_session_duty_shift_quota_failure_leaves_no_partial_shift(admin_session):
    # Regression test: shift creation succeeds and is flushed, but the
    # subsequent set_shift_quotas call fails (here, because the quota's
    # hierarchy node was deleted after parsing but before confirmation,
    # even though parsed_state still marks it "resolved": true). The row
    # must have zero effect overall — no orphaned DutyShift persisted
    # without its quotas.
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, f"{node.name}:3", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    admin_session.commit()

    assert sess.parsed_state["duty_shifts"][0]["node_quotas"][0]["resolved"] is True

    # Delete the node after parsing so parsed_state still says resolved=True
    # but set_shift_quotas will fail with "hierarchy node not found".
    admin_session.delete(admin_session.get(type(node), node.id))
    admin_session.commit()

    from app.db.models import DutyShift

    count_before = admin_session.execute(select(DutyShiftNodeQuota)).scalars().all()
    shifts_before = admin_session.execute(select(DutyShift)).scalars().all()

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["created"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["type"] == "duty_shifts"

    shifts_after = admin_session.execute(select(DutyShift)).scalars().all()
    assert len(shifts_after) == len(shifts_before)

    quotas_after = admin_session.execute(select(DutyShiftNodeQuota)).scalars().all()
    assert len(quotas_after) == len(count_before)

    assert sess.created_links["duty_shifts"] == []


def test_confirm_session_non_draft_raises(admin_session):
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
    sess.status = "confirmed"
    admin_session.commit()

    with pytest.raises(ImportSessionError, match="only draft sessions"):
        confirm_session(admin_session, session_id=sess.id, actor=admin)


def test_cancel_session_draft(admin_session):
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
    admin_session.commit()

    cancelled = cancel_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None


def test_mark_done_requires_confirmed(admin_session):
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
    admin_session.commit()

    with pytest.raises(ImportSessionError, match="confirmed"):
        mark_done(admin_session, session_id=sess.id, actor=admin)

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    assert result["created"] == 1

    done = mark_done(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    assert done.status == "done"


def test_reparse_resolves_duty_type_via_by_name_mapping(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    admin_session.commit()

    # Excel uses a different name than the DB
    wb = _wb_with_duty_shifts([
        ["excel_alias", loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    # Initially unresolved
    assert sess.parsed_state["duty_shifts"][0]["action"] == "error"

    # Apply by_name mapping
    set_selections(admin_session, session_id=sess.id, selections={
        "_name_mappings": {
            "duty_type": {"by_name": {"excel_alias": str(dt.id)}}
        }
    })
    admin_session.commit()

    sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["duty_shifts"][0]
    assert row["action"] == "new"
    assert row["resolved_duty_type_id"] == str(dt.id)


def test_reparse_by_row_overrides_by_name_for_duty_type(admin_session):
    dt_name = create_duty_type(admin_session, name=f"dt_name_{_uid()}", score_per_day=Decimal("1.00"))
    dt_row  = create_duty_type(admin_session, name=f"dt_row_{_uid()}",  score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        ["excel_alias", loc.name, "15.06.2024", "16.06.2024", "", "", 5, "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )

    row_number = sess.parsed_state["duty_shifts"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_name_mappings": {
            "duty_type": {
                "by_name": {"excel_alias": str(dt_name.id)},
                "by_row":  {f"duty_shifts:{row_number}": str(dt_row.id)},
            }
        }
    })
    admin_session.commit()

    sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
    assert sess.parsed_state["duty_shifts"][0]["resolved_duty_type_id"] == str(dt_row.id)


def test_reparse_resolves_hierarchy_node_via_by_name_mapping(admin_session):
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    admin_session.commit()

    wb = _wb_with_soldiers([
        ["1234567", "Test Soldier", "", "", "", "excel_node_alias", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    assert sess.parsed_state["soldiers"][0]["action"] == "error"

    set_selections(admin_session, session_id=sess.id, selections={
        "_name_mappings": {
            "hierarchy_node": {"by_name": {"excel_node_alias": str(node.id)}}
        }
    })
    admin_session.commit()

    sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
    row = sess.parsed_state["soldiers"][0]
    assert row["action"] == "new"
    assert row["hierarchy_node_id"] == str(node.id)


def test_reparse_resolves_quota_node_via_by_row_mapping(admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    admin_session.commit()

    wb = _wb_with_duty_shifts([
        [dt.name, loc.name, "15.06.2024", "16.06.2024", "", "", 5, "excel_quota_node:3", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(
        admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard",
    )
    initial_quotas = sess.parsed_state["duty_shifts"][0]["node_quotas"]
    assert initial_quotas[0]["resolved"] is False
    row_number = sess.parsed_state["duty_shifts"][0]["row"]

    set_selections(admin_session, session_id=sess.id, selections={
        "_name_mappings": {
            "hierarchy_node": {
                "by_row": {f"duty_shifts:{row_number}:excel_quota_node": str(node.id)}
            }
        }
    })
    admin_session.commit()

    sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
    quotas = sess.parsed_state["duty_shifts"][0]["node_quotas"]
    assert quotas[0]["resolved"] is True
    assert quotas[0]["node_id"] == str(node.id)


def test_reparse_bad_mapped_uuid_falls_back_to_name_lookup(admin_session):
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
    assert sess.parsed_state["duty_shifts"][0]["action"] == "new"  # baseline: resolves by name

    bad_uuid = str(uuid.uuid4())  # does not exist in DB
    set_selections(admin_session, session_id=sess.id, selections={
        "_name_mappings": {
            "duty_type": {"by_name": {dt.name: bad_uuid}}
        }
    })
    admin_session.commit()

    sess = reparse_session(admin_session, session_id=sess.id, actor=admin)
    # Bad UUID → not found in DB → fallback to name lookup → still resolves correctly
    assert sess.parsed_state["duty_shifts"][0]["action"] == "new"
    assert sess.parsed_state["duty_shifts"][0]["resolved_duty_type_id"] == str(dt.id)
