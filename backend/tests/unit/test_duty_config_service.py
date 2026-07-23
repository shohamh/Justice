from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.db.models import ExemptionDutyLocationMap, ExemptionDutyTypeMap, ExemptionType, SoldierExemption
from app.services.duty_config import (
    DutyConfigError,
    create_duty_type,
    create_exemption_type,
    create_location,
    delete_exemption_type,
    disable_exemption_type_and_revoke_all,
    list_exemption_duty_location_ids,
    map_exemption_to_duty_type,
    set_duty_type_active,
    set_exemption_duty_locations,
    set_exemption_duty_types,
    update_duty_type,
    update_exemption_type,
)
from tests.helpers import create_soldier


def test_create_duty_type(admin_session):
    dt = create_duty_type(admin_session, name="שמירה", score_per_day=Decimal("1.50"), actor_id=None)
    admin_session.commit()
    assert dt.name == "שמירה"
    assert dt.active is True
    row = admin_session.execute(
        text("SELECT action FROM audit_log WHERE action='duty_type.create' LIMIT 1")
    ).first()
    assert row is not None


def test_create_duty_type_rejects_duplicate_name(admin_session):
    create_duty_type(admin_session, name="ניקיון", score_per_day=Decimal("1.00"), actor_id=None)
    admin_session.flush()
    with pytest.raises(DutyConfigError):
        create_duty_type(admin_session, name="ניקיון", score_per_day=Decimal("2.00"), actor_id=None)


def test_create_duty_type_rejects_negative_score(admin_session):
    with pytest.raises(DutyConfigError):
        create_duty_type(admin_session, name="x", score_per_day=Decimal("-1"), actor_id=None)


def test_update_and_deactivate_duty_type(admin_session):
    dt = create_duty_type(admin_session, name="מטבח", score_per_day=Decimal("1.00"), actor_id=None)
    admin_session.flush()
    update_duty_type(
        admin_session,
        duty_type=dt,
        name="מטבח לילה",
        score_per_day=Decimal("2.50"),
        description="לילה",
        actor_id=None,
    )
    set_duty_type_active(admin_session, duty_type=dt, active=False, actor_id=None)
    admin_session.commit()
    assert dt.name == "מטבח לילה"
    assert dt.score_per_day == Decimal("2.50")
    assert dt.active is False


def test_create_location(admin_session):
    loc = create_location(admin_session, name="עמדת שער", base="בסיס דרום", actor_id=None)
    admin_session.commit()
    assert loc.name == "עמדת שער"
    assert loc.base == "בסיס דרום"
    assert loc.active is True


def test_create_exemption_type_and_map(admin_session):
    et = create_exemption_type(
        admin_session,
        name="פטור רפואי",
        is_medical=True,
        is_commander_exemption=True,
        actor_id=None,
    )
    dt = create_duty_type(admin_session, name="שמירה-מ", score_per_day=Decimal("1"), actor_id=None)
    admin_session.flush()
    assert et.is_medical is True
    assert et.is_commander_exemption is True
    map_exemption_to_duty_type(
        admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None
    )
    # idempotent: second call does not raise or duplicate
    map_exemption_to_duty_type(
        admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None
    )
    admin_session.commit()
    rows = admin_session.query(ExemptionDutyTypeMap).filter_by(exemption_type_id=et.id).all()
    assert len(rows) == 1

    update_exemption_type(
        admin_session,
        exemption_type=et,
        name=None,
        description=None,
        is_medical=False,
        is_commander_exemption=False,
        actor_id=None,
    )
    admin_session.commit()
    assert et.is_medical is False
    assert et.is_commander_exemption is False


def test_set_exemption_duty_types_diffs(admin_session):
    et = create_exemption_type(admin_session, name="פטור גב", actor_id=None)
    d1 = create_duty_type(admin_session, name="ניקיון-מ", score_per_day=Decimal("1"), actor_id=None)
    d2 = create_duty_type(admin_session, name="מטבח-מ", score_per_day=Decimal("1"), actor_id=None)
    admin_session.flush()
    set_exemption_duty_types(
        admin_session, exemption_type_id=et.id, duty_type_ids=[d1.id], actor_id=None
    )
    set_exemption_duty_types(
        admin_session, exemption_type_id=et.id, duty_type_ids=[d2.id], actor_id=None
    )
    admin_session.commit()
    rows = {
        r.duty_type_id
        for r in admin_session.query(ExemptionDutyTypeMap).filter_by(exemption_type_id=et.id)
    }
    assert rows == {d2.id}


def test_set_exemption_duty_locations_diffs(admin_session):
    et = create_exemption_type(admin_session, name="פטור מיקום", actor_id=None)
    l1 = create_location(admin_session, name="עמדה-מ1", actor_id=None)
    l2 = create_location(admin_session, name="עמדה-מ2", actor_id=None)
    admin_session.flush()
    set_exemption_duty_locations(
        admin_session, exemption_type_id=et.id, duty_location_ids=[l1.id], actor_id=None
    )
    admin_session.commit()
    assert list_exemption_duty_location_ids(admin_session, exemption_type_id=et.id) == [l1.id]

    set_exemption_duty_locations(
        admin_session, exemption_type_id=et.id, duty_location_ids=[l2.id], actor_id=None
    )
    admin_session.commit()
    rows = {
        r.duty_location_id
        for r in admin_session.query(ExemptionDutyLocationMap).filter_by(exemption_type_id=et.id)
    }
    assert rows == {l2.id}


def test_delete_exemption_type_rejected_when_granted(admin_session):
    et = create_exemption_type(admin_session, name="פטור בשימוש", actor_id=None)
    s = create_soldier(admin_session, personal_number="7200001")
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=s.id, exemption_type_id=et.id, start_date=date.today())
    )
    admin_session.flush()
    with pytest.raises(DutyConfigError):
        delete_exemption_type(admin_session, exemption_type=et, actor_id=None)


def test_disable_exemption_type_and_revoke_all(admin_session):
    et = ExemptionType(name="disable-bulk-test")
    admin_session.add(et)
    admin_session.flush()

    s1 = create_soldier(admin_session, personal_number="disable_bulk_1")
    s2 = create_soldier(admin_session, personal_number="disable_bulk_2")
    admin_session.add(SoldierExemption(
        soldier_id=s1.id, exemption_type_id=et.id,
        start_date=date.today() - timedelta(days=1), end_date=None,
    ))
    admin_session.add(SoldierExemption(
        soldier_id=s2.id, exemption_type_id=et.id,
        start_date=date.today() - timedelta(days=30), end_date=date.today() - timedelta(days=1),
    ))  # already expired — should NOT be revoked (no-op, shouldn't count)
    admin_session.flush()

    actor = create_soldier(admin_session, personal_number="disable_bulk_admin")
    count = disable_exemption_type_and_revoke_all(
        admin_session, exemption_type=et, reason="הסוג בוטל", actor_id=actor.id,
    )
    admin_session.commit()

    assert count == 1
    admin_session.refresh(et)
    assert et.active is False
    s1_ex = admin_session.execute(
        select(SoldierExemption).where(SoldierExemption.soldier_id == s1.id)
    ).scalar_one()
    assert s1_ex.revoked_at is not None
    assert s1_ex.revoke_reason == "הסוג בוטל"
