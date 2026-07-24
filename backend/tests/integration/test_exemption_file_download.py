from __future__ import annotations

from datetime import date

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import (
    ExemptionRequest,
    ExemptionRequestFile,
    ExemptionType,
    HierarchyLevelType,
)
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_node, create_soldier


def _level(session: Session, key: str, rank: int) -> HierarchyLevelType:
    """Insert a Hebrew-keyed level type, matching the real level keys the
    exemptions.medical_doc_min_* settings default to ("מדור"/"מרכז"). The
    shared _truncate_tables fixture pre-seeds English placeholder keys (see
    tests/conftest.py _LEVEL_TYPE_DEFAULTS) which don't match those defaults,
    so callers must clear them first (see _hebrew_levels below)."""
    lt = HierarchyLevelType(key=key, label=key, rank=rank)
    session.add(lt)
    session.flush()
    return lt


def _hebrew_levels(session: Session) -> None:
    session.execute(delete(HierarchyLevelType))
    session.flush()
    _level(session, "גדוד", 1)
    _level(session, "מרכז", 2)
    _level(session, "מדור", 3)
    _level(session, "צוות", 4)
    session.commit()


def _make_request_with_file(session: Session, soldier_id, *, is_medical: bool = True):
    et = ExemptionType(name=f"med-{soldier_id}", is_medical=is_medical)
    session.add(et)
    session.flush()
    req = ExemptionRequest(
        soldier_id=soldier_id,
        exemption_type_id=et.id,
        status="pending_commander",
        start_date=date(2026, 1, 1),
    )
    session.add(req)
    session.flush()
    f = ExemptionRequestFile(
        exemption_request_id=req.id,
        file_name="note.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4 test",
    )
    session.add(f)
    session.commit()
    return req, f


def test_medical_document_requires_minimum_commander_level(client, admin_session: Session):
    """A commander below the configured minimum level (a plain team/צוות
    commander, by default requiring מדור-and-above) cannot download a
    medical exemption's attached file, even though they're in the soldier's
    command chain and could otherwise see the exemption's other fields."""
    _hebrew_levels(admin_session)
    root = create_node(admin_session, level="מרכז", name="root_md")
    team = create_node(admin_session, level="צוות", name="team_md", parent=root)
    team_cmd = create_soldier(admin_session, personal_number="md_team_cmd", role="commander")
    team.commander_id = team_cmd.id
    admin_session.commit()

    soldier = create_soldier(admin_session, personal_number="md_soldier", hierarchy_node_id=team.id)
    req, f = _make_request_with_file(admin_session, soldier.id)

    r = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(team_cmd),
    )
    assert r.status_code == 403


def test_commander_at_minimum_level_can_download(client, admin_session: Session):
    """A מדור-level commander (at the configured default minimum) in the
    soldier's own command chain CAN download the file."""
    _hebrew_levels(admin_session)
    root = create_node(admin_session, level="מרכז", name="root_ok")
    mador = create_node(admin_session, level="מדור", name="mador_ok", parent=root)
    team = create_node(admin_session, level="צוות", name="team_ok", parent=mador)
    mador_cmd = create_soldier(admin_session, personal_number="md_mador_cmd", role="commander")
    mador.commander_id = mador_cmd.id
    admin_session.commit()

    soldier = create_soldier(admin_session, personal_number="md_soldier_ok", hierarchy_node_id=team.id)
    req, f = _make_request_with_file(admin_session, soldier.id)

    r = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(mador_cmd),
    )
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 test"


def test_soldier_can_download_own_medical_file(client, admin_session: Session):
    _hebrew_levels(admin_session)
    team = create_node(admin_session, level="צוות", name="team_self")
    soldier = create_soldier(admin_session, personal_number="md_self", hierarchy_node_id=team.id)
    req, f = _make_request_with_file(admin_session, soldier.id)

    r = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(soldier),
    )
    assert r.status_code == 200


def test_commander_out_of_scope_cannot_download(client, admin_session: Session):
    """A commander whose scope doesn't even contain the soldier's node is
    still rejected — the new level check must not bypass the scope check."""
    _hebrew_levels(admin_session)
    root = create_node(admin_session, level="מרכז", name="root_oos")
    other_root = create_node(admin_session, level="מרכז", name="other_root_oos")
    team = create_node(admin_session, level="צוות", name="team_oos", parent=root)
    outside_cmd = create_soldier(admin_session, personal_number="md_outside_cmd", role="commander")
    other_root.commander_id = outside_cmd.id
    admin_session.commit()

    soldier = create_soldier(admin_session, personal_number="md_soldier_oos", hierarchy_node_id=team.id)
    req, f = _make_request_with_file(admin_session, soldier.id)

    r = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(outside_cmd),
    )
    assert r.status_code == 403


def test_duty_manager_below_minimum_level_cannot_download(client, admin_session: Session):
    """A duty manager scoped below the configured minimum (default מרכז)
    cannot download the medical file."""
    _hebrew_levels(admin_session)
    root = create_node(admin_session, level="מרכז", name="root_dm")
    mador = create_node(admin_session, level="מדור", name="mador_dm", parent=root)
    team = create_node(admin_session, level="צוות", name="team_dm", parent=mador)
    dm = create_soldier(
        admin_session, personal_number="md_dm_low", role="duty_manager", hierarchy_node_id=mador.id,
    )
    admin_session.commit()

    soldier = create_soldier(admin_session, personal_number="md_soldier_dm_low", hierarchy_node_id=team.id)
    req, f = _make_request_with_file(admin_session, soldier.id)

    r = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(dm),
    )
    assert r.status_code == 403


def test_duty_manager_at_minimum_level_can_download(client, admin_session: Session):
    _hebrew_levels(admin_session)
    root = create_node(admin_session, level="מרכז", name="root_dm_ok")
    team = create_node(admin_session, level="צוות", name="team_dm_ok", parent=root)
    dm = create_soldier(
        admin_session, personal_number="md_dm_ok", role="duty_manager", hierarchy_node_id=root.id,
    )
    admin_session.commit()

    soldier = create_soldier(admin_session, personal_number="md_soldier_dm_ok", hierarchy_node_id=team.id)
    req, f = _make_request_with_file(admin_session, soldier.id)

    r = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(dm),
    )
    assert r.status_code == 200


def test_medical_doc_min_commander_level_configurable(client, admin_session: Session):
    """Lowering exemptions.medical_doc_min_commander_level to צוות allows a
    plain team commander (previously rejected) to download the file."""
    _hebrew_levels(admin_session)
    root = create_node(admin_session, level="מרכז", name="root_cfg")
    team = create_node(admin_session, level="צוות", name="team_cfg", parent=root)
    team_cmd = create_soldier(admin_session, personal_number="md_team_cfg", role="commander")
    team.commander_id = team_cmd.id
    admin_session.commit()

    soldier = create_soldier(admin_session, personal_number="md_soldier_cfg", hierarchy_node_id=team.id)
    req, f = _make_request_with_file(admin_session, soldier.id)

    r = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(team_cmd),
    )
    assert r.status_code == 403

    set_setting(admin_session, "exemptions.medical_doc_min_commander_level", "צוות", actor_id=None)
    admin_session.commit()

    r2 = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(team_cmd),
    )
    assert r2.status_code == 200
