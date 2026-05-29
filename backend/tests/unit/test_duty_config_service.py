from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.duty_config import (
    DutyConfigError,
    create_duty_type,
    create_location,
    set_duty_type_active,
    update_duty_type,
)


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
    update_duty_type(admin_session, duty_type=dt, name="מטבח לילה", score_per_day=Decimal("2.50"),
                     description="לילה", actor_id=None)
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


from decimal import Decimal as _D

from app.services.duty_config import (
    create_exemption_type,
    delete_exemption_type,
    map_exemption_to_duty_type,
    set_exemption_duty_types,
    unmap_exemption_from_duty_type,
)


def test_create_exemption_type_and_map(admin_session):
    et = create_exemption_type(admin_session, name="פטור רפואי", actor_id=None)
    dt = create_duty_type(admin_session, name="שמירה-מ", score_per_day=_D("1"), actor_id=None)
    admin_session.flush()
    map_exemption_to_duty_type(admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None)
    # idempotent: second call does not raise or duplicate
    map_exemption_to_duty_type(admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None)
    admin_session.commit()
    from app.db.models import ExemptionDutyTypeMap
    rows = admin_session.query(ExemptionDutyTypeMap).filter_by(exemption_type_id=et.id).all()
    assert len(rows) == 1


def test_set_exemption_duty_types_diffs(admin_session):
    et = create_exemption_type(admin_session, name="פטור גב", actor_id=None)
    d1 = create_duty_type(admin_session, name="ניקיון-מ", score_per_day=_D("1"), actor_id=None)
    d2 = create_duty_type(admin_session, name="מטבח-מ", score_per_day=_D("1"), actor_id=None)
    admin_session.flush()
    set_exemption_duty_types(admin_session, exemption_type_id=et.id, duty_type_ids=[d1.id], actor_id=None)
    set_exemption_duty_types(admin_session, exemption_type_id=et.id, duty_type_ids=[d2.id], actor_id=None)
    admin_session.commit()
    from app.db.models import ExemptionDutyTypeMap
    rows = {r.duty_type_id for r in admin_session.query(ExemptionDutyTypeMap).filter_by(exemption_type_id=et.id)}
    assert rows == {d2.id}


def test_delete_exemption_type_rejected_when_granted(admin_session):
    from tests.helpers import create_soldier
    from app.db.models import SoldierExemption
    from datetime import date
    et = create_exemption_type(admin_session, name="פטור בשימוש", actor_id=None)
    s = create_soldier(admin_session, personal_number="7200001")
    admin_session.flush()
    admin_session.add(SoldierExemption(soldier_id=s.id, exemption_type_id=et.id, start_date=date.today()))
    admin_session.flush()
    with pytest.raises(DutyConfigError):
        delete_exemption_type(admin_session, exemption_type=et, actor_id=None)
