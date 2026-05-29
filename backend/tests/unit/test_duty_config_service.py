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
