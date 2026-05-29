from decimal import Decimal

import pytest

from app.services.adjustments import AdjustmentError, create_adjustment, list_adjustments
from tests.helpers import create_soldier


def test_create_positive_and_negative(admin_session):
    s = create_soldier(admin_session, personal_number="8300001")
    create_adjustment(
        admin_session, soldier_id=s.id, delta=Decimal("2.5"), reason="פיצוי", actor_id=None
    )
    create_adjustment(
        admin_session, soldier_id=s.id, delta=Decimal("-1.0"), reason="תיקון", actor_id=None
    )
    admin_session.commit()
    rows = list_adjustments(admin_session, soldier_id=s.id)
    assert {r.delta for r in rows} == {Decimal("2.50"), Decimal("-1.00")}


def test_zero_delta_rejected(admin_session):
    s = create_soldier(admin_session, personal_number="8300002")
    with pytest.raises(AdjustmentError):
        create_adjustment(
            admin_session, soldier_id=s.id, delta=Decimal("0"), reason="x", actor_id=None
        )


def test_empty_reason_rejected(admin_session):
    s = create_soldier(admin_session, personal_number="8300003")
    with pytest.raises(AdjustmentError):
        create_adjustment(
            admin_session, soldier_id=s.id, delta=Decimal("1"), reason="  ", actor_id=None
        )


def test_unknown_soldier_rejected(admin_session):
    import uuid

    with pytest.raises(AdjustmentError):
        create_adjustment(
            admin_session, soldier_id=uuid.uuid4(), delta=Decimal("1"), reason="x", actor_id=None
        )
