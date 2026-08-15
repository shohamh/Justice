from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from app.db.models import HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from app.services.invite_codes import create_invite_code
from app.services.rank_advancement import upsert_interval
from tests.helpers import create_node


def _uid():
    return uuid.uuid4().hex[:8]


def _personal_number():
    return str(uuid.uuid4().int % 90_000_000 + 10_000_000)


def _post_register(client, payload, files=None):
    return client.post(
        "/api/auth/register",
        data={"payload": json.dumps(payload)},
        files=files or [],
    )


def _setup_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _payload(invite_code, node_id, **overrides):
    return {
        "invite_code": invite_code,
        "personal_number": _personal_number(),
        "full_name": "Test Soldier",
        "password": "secure-password-1",
        "phone": "050-1234567",
        "email": "soldier@example.com",
        "gender": "male",
        "is_officer": False,
        "rank": "טוראי",
        # Relative to today so a חובה-only rank never accidentally looks like it
        # outlived its own mandatory-service window as the real calendar advances.
        "enlistment_date": (date.today() - timedelta(days=600)).isoformat(),
        "mandatory_end_date": (date.today() + timedelta(days=200)).isoformat(),
        "discharge_date": (date.today() + timedelta(days=600)).isoformat(),
        "last_mitvahim_date": (date.today() - timedelta(days=30)).isoformat(),
        "last_alal_date": None,
        "requested_node_id": str(node_id),
        "exemption_requests": [],
        "personal_constraints": [],
        **overrides,
    }


def test_register_rejects_missing_phone(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(invite.code, node.id)
    del payload["phone"]
    resp = _post_register(client, payload)
    assert resp.status_code == 422


def test_register_reports_short_password_as_password_policy(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(invite.code, node.id, password="short7")
    resp = _post_register(client, payload)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "password_policy"


def test_register_rejects_invalid_phone_format(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(invite.code, node.id, phone="not-a-phone-number")
    resp = _post_register(client, payload)
    assert resp.status_code == 422


def test_register_stores_military_driving_license(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(
        invite.code, node.id,
        has_military_driving_license=True,
        military_driving_license_expiry=(date.today() + timedelta(days=365)).isoformat(),
    )
    resp = _post_register(client, payload)
    assert resp.status_code == 200

    from app.db.models import Soldier
    soldier = admin_session.query(Soldier).filter_by(personal_number=payload["personal_number"]).one()
    assert soldier.has_military_driving_license is True
    assert soldier.military_driving_license_expiry == date.today() + timedelta(days=365)


def test_register_defaults_military_driving_license_to_false(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(invite.code, node.id)
    resp = _post_register(client, payload)
    assert resp.status_code == 200

    from app.db.models import Soldier
    soldier = admin_session.query(Soldier).filter_by(personal_number=payload["personal_number"]).one()
    assert soldier.has_military_driving_license is False
    assert soldier.military_driving_license_expiry is None


def test_register_returns_access_token(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    resp = _post_register(client, _payload(invite.code, node.id))
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_register_exhausted_code_returns_400(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=0, actor_id=None)
    admin_session.commit()

    resp = _post_register(client, _payload(invite.code, node.id))
    assert resp.status_code == 400


def test_validate_code_endpoint(client, admin_session):
    invite = create_invite_code(admin_session, uses_left=3, actor_id=None)
    admin_session.commit()
    assert client.get(f"/api/auth/register/validate-code?code={invite.code}").json()["valid"] is True
    assert client.get("/api/auth/register/validate-code?code=INVALID1").json()["valid"] is False


def test_register_nodes_returns_list(client, admin_session):
    create_node(admin_session, level="division", name=f"div_{_uid()}")
    invite = create_invite_code(admin_session, uses_left=3, actor_id=None)
    admin_session.commit()
    resp = client.get(f"/api/auth/register/nodes?invite_code={invite.code}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_validate_code_is_rate_limited_per_ip(client, admin_session, monkeypatch):
    from app.settings import get_settings
    from app.rate_limit import limiter

    monkeypatch.setenv("INVITE_CODE_RATE_LIMIT", "2/minute")
    get_settings.cache_clear()
    limiter.reset()
    try:
        invite = create_invite_code(admin_session, uses_left=3, actor_id=None)
        admin_session.commit()

        for _ in range(2):
            r = client.get(f"/api/auth/register/validate-code?code={invite.code}")
            assert r.status_code == 200

        r = client.get(f"/api/auth/register/validate-code?code={invite.code}")
        assert r.status_code == 429
    finally:
        get_settings.cache_clear()
        limiter.reset()


def test_register_nodes_is_rate_limited_per_ip(client, admin_session, monkeypatch):
    from app.settings import get_settings
    from app.rate_limit import limiter

    monkeypatch.setenv("INVITE_CODE_RATE_LIMIT", "2/minute")
    get_settings.cache_clear()
    limiter.reset()
    try:
        invite = create_invite_code(admin_session, uses_left=3, actor_id=None)
        admin_session.commit()

        for _ in range(2):
            r = client.get(f"/api/auth/register/nodes?invite_code={invite.code}")
            assert r.status_code == 200

        r = client.get(f"/api/auth/register/nodes?invite_code={invite.code}")
        assert r.status_code == 429
    finally:
        get_settings.cache_clear()
        limiter.reset()


def test_register_nodes_rejects_missing_code(client):
    resp = client.get("/api/auth/register/nodes")
    assert resp.status_code == 422


def test_register_nodes_rejects_invalid_code(client):
    resp = client.get("/api/auth/register/nodes?invite_code=INVALID-CODE-XYZ")
    assert resp.status_code == 403


def test_register_rejects_partial_exemption_request(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    payload = _payload(
        invite.code, node.id,
        exemption_requests=[{"exemption_type_id": "", "start_date": "", "end_date": "", "reason": ""}],
    )
    resp = _post_register(client, payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "exemption_missing_fields"


def test_register_accepts_permanent_exemption_row(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    from app.db.models import ExemptionType
    et = ExemptionType(name=f"פטור-reg-permanent-{_uid()}", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    payload = _payload(invite.code, node.id, exemption_requests=[
        {"exemption_type_id": str(et.id), "start_date": None, "end_date": None, "reason": "פטור קבוע"},
    ])
    resp = _post_register(client, payload)
    assert resp.status_code == 200, resp.text

    from app.db.models import ExemptionRequest
    req = admin_session.query(ExemptionRequest).filter_by(exemption_type_id=et.id).one()
    assert req.start_date is None
    assert req.end_date is None


def test_register_rejects_exemption_row_with_end_date_but_no_start_date(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    from app.db.models import ExemptionType
    et = ExemptionType(name=f"פטור-reg-badrow-{_uid()}", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    payload = _payload(invite.code, node.id, exemption_requests=[
        {"exemption_type_id": str(et.id), "start_date": None,
         "end_date": (date.today() + timedelta(days=10)).isoformat(), "reason": "x"},
    ])
    resp = _post_register(client, payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "start_date_required"


def test_public_exemption_types_expose_is_medical(client, admin_session):
    from app.db.models import ExemptionType
    et = ExemptionType(name=f"פטור-medical-{_uid()}", is_commander_exemption=False, is_medical=True)
    admin_session.add(et)
    admin_session.commit()

    resp = client.get("/api/auth/exemption-types")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == str(et.id))
    assert row["is_medical"] is True


def test_register_rejects_medical_exemption_row_without_file(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    from app.db.models import ExemptionType
    et = ExemptionType(name=f"פטור-reg-medical-{_uid()}", is_commander_exemption=False, is_medical=True)
    admin_session.add(et)
    admin_session.commit()

    payload = _payload(invite.code, node.id, exemption_requests=[
        {"exemption_type_id": str(et.id), "start_date": date.today().isoformat(), "end_date": None, "reason": "רפואי"},
    ])
    resp = _post_register(client, payload)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "medical_exemption_requires_file"

    # Nothing should have been persisted — the whole registration is atomic.
    from app.db.models import Soldier
    assert admin_session.query(Soldier).filter_by(personal_number=payload["personal_number"]).first() is None


def test_register_accepts_medical_exemption_row_with_file(client, admin_session):
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    from app.db.models import ExemptionType
    et = ExemptionType(name=f"פטור-reg-medical2-{_uid()}", is_commander_exemption=False, is_medical=True)
    admin_session.add(et)
    admin_session.commit()

    payload = _payload(invite.code, node.id, exemption_requests=[
        {"exemption_type_id": str(et.id), "start_date": date.today().isoformat(), "end_date": None, "reason": "רפואי"},
    ])
    resp = _post_register(client, payload, files=[
        ("exemption_files_0", ("doc.pdf", b"%PDF-1.4 fake but valid header", "application/pdf")),
    ])
    assert resp.status_code == 200, resp.text

    from app.db.models import ExemptionRequest, ExemptionRequestFile
    req = admin_session.query(ExemptionRequest).filter_by(exemption_type_id=et.id).one()
    assert admin_session.query(ExemptionRequestFile).filter_by(exemption_request_id=req.id).count() == 1


def test_register_initializes_cumulative_next_rank_date_from_enlistment_date(client, admin_session):
    """Task 13: register() is one of the writers of Soldier.rank — it must
    initialize next_rank_date/current_rank_since the same way
    update_soldier_profile does, using enlistment_date as the since-anchor
    when one was supplied at registration."""
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    enlistment = date(2021, 1, 15)
    payload = _payload(invite.code, node.id, rank="סמר", enlistment_date=enlistment.isoformat())
    resp = _post_register(client, payload)
    assert resp.status_code == 200, resp.text

    from app.db.models import Soldier
    soldier = admin_session.query(Soldier).filter_by(personal_number=payload["personal_number"]).one()
    assert soldier.current_rank_since == enlistment
    assert soldier.next_rank_date == date(2025, 9, 15)
    assert soldier.next_rank_date_overridden is False


def test_register_with_disabled_interval_leaves_next_rank_date_none(client, admin_session):
    """An explicitly disabled interval leaves registration unscheduled."""
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    upsert_interval(
        admin_session, track="enlisted", rank="טוראי", months_to_next=None,
        advance_on_career_entry=False, actor_id=None,
    )
    admin_session.commit()

    payload = _payload(invite.code, node.id)
    resp = _post_register(client, payload)
    assert resp.status_code == 200, resp.text

    from app.db.models import Soldier
    soldier = admin_session.query(Soldier).filter_by(personal_number=payload["personal_number"]).one()
    assert soldier.next_rank_date is None
    assert soldier.current_rank_since is not None
    assert soldier.next_rank_date_overridden is False


def test_register_matches_files_to_correct_row_with_multiple_exemption_rows(client, admin_session):
    # Regression test: ExemptionRequest.id is a random UUID with no relation
    # to insertion order, so files must be matched to rows using the order
    # reg_svc.register() returns them in — not by re-querying and sorting by id.
    holding = _setup_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    invite = create_invite_code(admin_session, uses_left=1, actor_id=None)
    admin_session.commit()

    from app.db.models import ExemptionType
    et_medical_a = ExemptionType(name=f"פטור-reg-multi-a-{_uid()}", is_commander_exemption=False, is_medical=True)
    et_plain = ExemptionType(name=f"פטור-reg-multi-b-{_uid()}", is_commander_exemption=False, is_medical=False)
    et_medical_c = ExemptionType(name=f"פטור-reg-multi-c-{_uid()}", is_commander_exemption=False, is_medical=True)
    admin_session.add_all([et_medical_a, et_plain, et_medical_c])
    admin_session.commit()

    payload = _payload(invite.code, node.id, exemption_requests=[
        {"exemption_type_id": str(et_medical_a.id), "start_date": date.today().isoformat(), "end_date": None, "reason": "a"},
        {"exemption_type_id": str(et_plain.id), "start_date": date.today().isoformat(), "end_date": None, "reason": "b"},
        {"exemption_type_id": str(et_medical_c.id), "start_date": date.today().isoformat(), "end_date": None, "reason": "c"},
    ])
    resp = _post_register(client, payload, files=[
        ("exemption_files_0", ("file-a.pdf", b"%PDF-1.4 file for row a", "application/pdf")),
        ("exemption_files_2", ("file-c.pdf", b"%PDF-1.4 file for row c", "application/pdf")),
    ])
    assert resp.status_code == 200, resp.text

    from app.db.models import ExemptionRequest, ExemptionRequestFile
    req_a = admin_session.query(ExemptionRequest).filter_by(exemption_type_id=et_medical_a.id).one()
    req_b = admin_session.query(ExemptionRequest).filter_by(exemption_type_id=et_plain.id).one()
    req_c = admin_session.query(ExemptionRequest).filter_by(exemption_type_id=et_medical_c.id).one()

    files_a = admin_session.query(ExemptionRequestFile).filter_by(exemption_request_id=req_a.id).all()
    files_b = admin_session.query(ExemptionRequestFile).filter_by(exemption_request_id=req_b.id).all()
    files_c = admin_session.query(ExemptionRequestFile).filter_by(exemption_request_id=req_c.id).all()

    assert [f.file_name for f in files_a] == ["file-a.pdf"]
    assert files_b == []
    assert [f.file_name for f in files_c] == ["file-c.pdf"]
