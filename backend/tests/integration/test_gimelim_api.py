from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyReserveLink,
    DutyShift,
    DutyType,
    SystemSetting,
)
from tests.helpers import auth_headers, create_node, create_soldier


# ── Shared setup helpers ──────────────────────────────────────────────────────

def _make_dt_loc(session: Session, suffix: str):
    dt = DutyType(name=f"dt_{suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{suffix}")
    session.add(dt)
    session.add(loc)
    session.flush()
    return dt, loc


def _make_shift(session: Session, dt: DutyType, loc: DutyLocation, start: str, end: str) -> DutyShift:
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start,
        end_date=end,
    )
    session.add(shift)
    session.flush()
    return shift


def _make_assignment(
    session: Session,
    soldier_id: uuid.UUID,
    dt: DutyType,
    loc: DutyLocation,
    shift: DutyShift,
    *,
    is_reserve: bool = False,
    status: str = "published",
) -> DutyAssignment:
    a = DutyAssignment(
        soldier_id=soldier_id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=shift.start_date,
        end_date=shift.end_date,
        status=status,
        is_reserve=is_reserve,
        duty_shift_id=shift.id,
    )
    session.add(a)
    session.flush()
    return a


def _link_reserve(session: Session, primary: DutyAssignment, reserve: DutyAssignment) -> None:
    link = DutyReserveLink(
        primary_assignment_id=primary.id,
        reserve_assignment_id=reserve.id,
        hierarchy_distance=0,
    )
    session.add(link)
    session.flush()


def _set_gimelim_enabled(session: Session, enabled: bool) -> None:
    import json
    setting = session.get(SystemSetting, "gimalim.enabled")
    if setting is None:
        setting = SystemSetting(key="gimalim.enabled", value=enabled)
        session.add(setting)
    else:
        setting.value = enabled
    session.flush()


# ── Test 1: Preview returns 403 when gimelim is disabled ─────────────────────

def test_preview_returns_403_when_disabled(client: TestClient, admin_session: Session):
    _set_gimelim_enabled(admin_session, False)

    node = create_node(admin_session, level="branch", name="n_gim001")
    admin = create_soldier(admin_session, personal_number="gim001_adm", role="admin", hierarchy_node_id=node.id)
    soldier_a = create_soldier(admin_session, personal_number="gim001_a", hierarchy_node_id=node.id)
    dt, loc = _make_dt_loc(admin_session, "gim001")
    shift = _make_shift(admin_session, dt, loc, "2030-03-01", "2030-03-05")
    primary_a = _make_assignment(admin_session, soldier_a.id, dt, loc, shift)
    admin_session.commit()

    resp = client.post(
        f"/api/shifts/{shift.id}/gimelim/preview",
        json={"primary_assignment_id": str(primary_a.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "gimelim_disabled"


# ── Test 2: Preview returns 400 when no reserve is linked ─────────────────────

def test_preview_returns_400_no_reserve_linked(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="branch", name="n_gim002")
    admin = create_soldier(admin_session, personal_number="gim002_adm", role="admin", hierarchy_node_id=node.id)
    soldier_a = create_soldier(admin_session, personal_number="gim002_a", hierarchy_node_id=node.id)
    dt, loc = _make_dt_loc(admin_session, "gim002")
    shift = _make_shift(admin_session, dt, loc, "2030-04-01", "2030-04-05")
    primary_a = _make_assignment(admin_session, soldier_a.id, dt, loc, shift)
    # Intentionally no reserve linked
    admin_session.commit()

    resp = client.post(
        f"/api/shifts/{shift.id}/gimelim/preview",
        json={"primary_assignment_id": str(primary_a.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400
    assert "no_reserve_linked" in resp.json()["detail"]


# ── Test 3: Preview 200 with future_assignment=null when no future slot ───────

def test_preview_no_future_slot(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="branch", name="n_gim003")
    admin = create_soldier(admin_session, personal_number="gim003_adm", role="admin", hierarchy_node_id=node.id)
    soldier_a = create_soldier(admin_session, personal_number="gim003_a", hierarchy_node_id=node.id)
    soldier_b = create_soldier(admin_session, personal_number="gim003_b", hierarchy_node_id=node.id)
    dt, loc = _make_dt_loc(admin_session, "gim003")
    shift = _make_shift(admin_session, dt, loc, "2030-05-01", "2030-05-05")
    primary_a = _make_assignment(admin_session, soldier_a.id, dt, loc, shift, is_reserve=False)
    reserve_b = _make_assignment(admin_session, soldier_b.id, dt, loc, shift, is_reserve=True)
    _link_reserve(admin_session, primary_a, reserve_b)
    # No future shifts of the same duty type exist
    admin_session.commit()

    resp = client.post(
        f"/api/shifts/{shift.id}/gimelim/preview",
        json={"primary_assignment_id": str(primary_a.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["future_assignment"] is None
    assert "no_future_slot_found" in data["warnings"]
    assert "preview_token" in data


# ── Test 4: Full preview → commit flow ────────────────────────────────────────

def test_preview_then_commit(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="branch", name="n_gim004")
    admin = create_soldier(admin_session, personal_number="gim004_adm", role="admin", hierarchy_node_id=node.id)
    soldier_a = create_soldier(admin_session, personal_number="gim004_a", hierarchy_node_id=node.id)
    soldier_b = create_soldier(admin_session, personal_number="gim004_b", hierarchy_node_id=node.id)
    soldier_c = create_soldier(admin_session, personal_number="gim004_c", hierarchy_node_id=node.id)
    soldier_d = create_soldier(admin_session, personal_number="gim004_d", hierarchy_node_id=node.id)
    dt, loc = _make_dt_loc(admin_session, "gim004")

    # Current shift: A (primary) + B (reserve)
    current_shift = _make_shift(admin_session, dt, loc, "2030-06-01", "2030-06-05")
    primary_a = _make_assignment(admin_session, soldier_a.id, dt, loc, current_shift, is_reserve=False)
    reserve_b = _make_assignment(admin_session, soldier_b.id, dt, loc, current_shift, is_reserve=True)
    _link_reserve(admin_session, primary_a, reserve_b)

    # Future shift: C (primary) + D (reserve)
    future_shift = _make_shift(admin_session, dt, loc, "2030-08-01", "2030-08-05")
    primary_c = _make_assignment(admin_session, soldier_c.id, dt, loc, future_shift, is_reserve=False)
    reserve_d = _make_assignment(admin_session, soldier_d.id, dt, loc, future_shift, is_reserve=True)
    _link_reserve(admin_session, primary_c, reserve_d)

    admin_session.commit()

    # Preview
    preview_resp = client.post(
        f"/api/shifts/{current_shift.id}/gimelim/preview",
        json={"primary_assignment_id": str(primary_a.id), "rest_days": 7},
        headers=auth_headers(admin),
    )
    assert preview_resp.status_code == 200, preview_resp.text
    preview_data = preview_resp.json()
    token = preview_data["preview_token"]

    # Commit
    commit_resp = client.post(
        f"/api/shifts/{current_shift.id}/gimelim/commit",
        json={"preview_token": token},
        headers=auth_headers(admin),
    )
    assert commit_resp.status_code == 200, commit_resp.text
    commit_data = commit_resp.json()
    assert commit_data["dismissal_id"] is not None
    assert commit_data["call_up_assignment_id"] is not None
    assert commit_data["future_primary_assignment_id"] is not None
    assert commit_data["future_demoted_assignment_id"] is not None


# ── Test 5: Commit returns 400 on unknown token ───────────────────────────────

def test_commit_returns_400_on_unknown_token(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="branch", name="n_gim005")
    admin = create_soldier(admin_session, personal_number="gim005_adm", role="admin", hierarchy_node_id=node.id)
    dt, loc = _make_dt_loc(admin_session, "gim005")
    shift = _make_shift(admin_session, dt, loc, "2030-07-01", "2030-07-05")
    admin_session.commit()

    resp = client.post(
        f"/api/shifts/{shift.id}/gimelim/commit",
        json={"preview_token": "bad-token-that-does-not-exist"},
        headers=auth_headers(admin),
    )
    # token_not_found → 400 (not 409; 409 is only for stale/expired)
    assert resp.status_code == 400
    assert "token_not_found" in resp.json()["detail"]
