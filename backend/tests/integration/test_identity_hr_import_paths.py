"""HR sync and import write paths store canonical email + ad_username together."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.db.models import HierarchyNode, Soldier
from app.services.hr.mapping import MappedSoldierFields
from app.services.hr.person_sync import _apply_new_person
from app.services.hr.schemas import HrUser
from app.services.identity_write import BulkIdentityCheck, assign_soldier_email
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _holding(session):
    node = HierarchyNode(level="unit", name=f"Holding_{_uid()}", parent_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    set_setting(session, "system.holding_node_id", str(node.id), actor_id=None)
    session.commit()


def _hr(pn):
    return HrUser(
        full_name="ישראל ישראלי", personal_number=pn,
        team_id=None, mador_id=None, branch_id=None,
        department_id=None, shetach_id=None, unit_id=None,
    )


def _mapped(pn, email, full_name="ישראל ישראלי"):
    return MappedSoldierFields(full_name=full_name, personal_number=pn, email=email)


def _owner(session, email):
    s = create_soldier(session, personal_number=f"own_{_uid()}")
    assign_soldier_email(session, s, email)
    session.commit()
    return s


# ── HR sync ─────────────────────────────────────────────────────────────────


def test_hr_new_person_gets_canonical_email_and_ad_username(admin_session):
    _holding(admin_session)
    soldier, _ = _apply_new_person(admin_session, _hr("hr-1"), _mapped("hr-1", " Dude@Gmail.COM "))
    admin_session.commit()
    assert (soldier.email, soldier.ad_username) == ("dude@gmail.com", "dude")


def test_hr_existing_person_email_change_is_canonical_and_unverifies(admin_session):
    _holding(admin_session)
    existing = create_soldier(admin_session, personal_number="hr-2")
    assign_soldier_email(admin_session, existing, "old@example.com")
    existing.email_verified = True
    admin_session.commit()
    soldier, _ = _apply_new_person(admin_session, _hr("hr-2"), _mapped("hr-2", "New.Mail@Example.com"))
    admin_session.commit()
    assert (soldier.email, soldier.ad_username, soldier.email_verified) == (
        "new.mail@example.com", "new.mail", False,
    )


def test_hr_colliding_email_is_not_applied_but_other_fields_sync(admin_session, caplog):
    _holding(admin_session)
    _owner(admin_session, "taken@example.com")
    existing = create_soldier(admin_session, personal_number="hr-3", full_name="שם ישן")
    with caplog.at_level(logging.WARNING, logger="app.services.hr.person_sync"):
        soldier, _ = _apply_new_person(
            admin_session, _hr("hr-3"), _mapped("hr-3", "TAKEN@example.com", full_name="שם חדש")
        )
        admin_session.commit()
    assert soldier.id == existing.id
    assert soldier.full_name == "שם חדש"
    assert (soldier.email, soldier.ad_username) == (None, None)
    assert "taken@example.com" not in caplog.text.lower()


def test_hr_unsupported_email_for_new_person_creates_soldier_without_email(admin_session):
    _holding(admin_session)
    soldier, _ = _apply_new_person(admin_session, _hr("hr-4"), _mapped("hr-4", "not-an-email"))
    admin_session.commit()
    assert soldier.id is not None
    assert (soldier.email, soldier.ad_username) == (None, None)


# ── Bulk preview check ──────────────────────────────────────────────────────


def test_bulk_identity_check_codes(admin_session):
    owner = _owner(admin_session, "taken@example.com")
    check = BulkIdentityCheck(admin_session.execute(select(Soldier)).scalars())
    assert check.check("nope") == "email_invalid"
    assert check.check("a+b@example.com") == "ad_username_invalid"
    assert check.check("TAKEN@example.com") == "email_taken"
    assert check.check("taken@corp.example") == "ad_username_taken"
    assert check.check("taken@example.com", own_soldier_id=owner.id) is None
    assert check.check(None) is None
    assert check.check("fresh@example.com") is None
    assert check.check("Fresh@example.com") == "email_duplicate_in_file"


# ── Excel import apply ──────────────────────────────────────────────────────


def _apply_rows(client, dm, rows):
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    return client.post(
        "/api/import/apply",
        json={"soldiers": rows, "assignments": []},
        headers={"Authorization": f"Bearer {token}"},
    )


def _row(node, pn, email, action="new", existing_id=None, row=2):
    return {
        "row": row, "action": action, "personal_number": pn, "full_name": "טסט יחידה",
        "rank": None, "gender": None, "is_officer": None,
        "hierarchy_node_id": str(node.id), "enrolled_at": None,
        "enlistment_date": None, "phone": None, "email": email,
        "existing_id": str(existing_id) if existing_id else None,
    }


def test_excel_apply_new_row_stores_canonical_pair_and_reports_collisions(client, admin_session):
    node = create_node(admin_session, level="branch", name=f"ii_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"ii_dm_{_uid()}", role="duty_manager",
                        hierarchy_node_id=node.id)
    _owner(admin_session, "taken@example.com")
    resp = _apply_rows(client, dm, [
        _row(node, "ii_ok_1", " Fresh.One@Example.com ", row=2),
        _row(node, "ii_dup_1", "TAKEN@example.com", row=3),
        _row(node, "ii_bad_1", "nope", row=4),
        _row(node, "ii_dup_2", "fresh.one@example.com", row=5),
    ])
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == 1
    assert sorted(body["errors"]) == sorted([
        "Row 3: email_taken", "Row 4: email_invalid", "Row 5: email_taken",
    ])
    s = admin_session.execute(select(Soldier).where(Soldier.personal_number == "ii_ok_1")).scalar_one()
    assert (s.email, s.ad_username) == ("fresh.one@example.com", "fresh.one")
    for pn in ("ii_dup_1", "ii_bad_1", "ii_dup_2"):
        assert admin_session.execute(select(Soldier).where(Soldier.personal_number == pn)).first() is None


def test_excel_apply_update_row_with_collision_leaves_soldier_untouched(client, admin_session):
    node = create_node(admin_session, level="branch", name=f"ii_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"ii_dm_{_uid()}", role="duty_manager",
                        hierarchy_node_id=node.id)
    _owner(admin_session, "taken@example.com")
    target = create_soldier(admin_session, personal_number=f"ii_t_{_uid()}", hierarchy_node_id=node.id,
                            full_name="שם מקורי")
    resp = _apply_rows(client, dm, [_row(node, target.personal_number, "taken@example.com",
                                        action="update", existing_id=target.id)])
    assert resp.status_code == 200
    assert resp.json()["errors"] == [f"Row 2: email_taken"]
    admin_session.expire_all()
    target = admin_session.get(Soldier, target.id)
    assert target.full_name == "שם מקורי"
    assert target.email is None


# ── Import session (preview + confirm) ──────────────────────────────────────


def test_import_session_preview_flags_and_confirm_stores_canonical_pair(client, admin_session):
    import io

    import openpyxl

    import app.services.import_parsers.v1_standard  # noqa: F401  (registers parser)

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    _owner(admin_session, "taken@example.com")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("soldiers")
    ws.append(["personal_number", "full_name", "email"])
    ws.append(["is_ok_1", "טסט ראשון", " Sess.User@Example.com "])
    ws.append(["is_dup_1", "טסט שני", "TAKEN@example.com"])
    ws.append(["is_bad_1", "טסט שלישי", "nope"])
    buf = io.BytesIO()
    wb.save(buf)
    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.post(
        "/api/import/sessions?parser_id=v1_standard",
        files={"file": ("import.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (200, 201), resp.text
    session_id = resp.json()["session_id"]
    detail = client.get(f"/api/import/sessions/{session_id}", headers={"Authorization": f"Bearer {token}"})
    rows = {r["personal_number"]: r for r in detail.json()["parsed_state"]["soldiers"]}
    assert rows["is_ok_1"]["action"] == "new"
    assert rows["is_dup_1"]["action"] == "error"
    assert rows["is_bad_1"]["action"] == "error"

    confirmed = client.post(f"/api/import/sessions/{session_id}/confirm",
                            headers={"Authorization": f"Bearer {token}"})
    assert confirmed.status_code == 200
    s = admin_session.execute(select(Soldier).where(Soldier.personal_number == "is_ok_1")).scalar_one()
    assert (s.email, s.ad_username) == ("sess.user@example.com", "sess.user")
