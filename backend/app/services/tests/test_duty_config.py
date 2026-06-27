from __future__ import annotations

from decimal import Decimal

from app.services.duty_config import create_duty_type, update_duty_type
from tests.helpers import create_node


def test_create_duty_type_with_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_dt1")
    dt = create_duty_type(
        admin_session,
        name="dt_with_scope",
        score_per_day=Decimal("1.00"),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert dt.eligible_node_ids == [node.id]


def test_create_duty_type_without_eligible_node_ids_defaults_to_none(admin_session):
    dt = create_duty_type(admin_session, name="dt_unscoped", score_per_day=Decimal("1.00"))
    admin_session.commit()
    assert dt.eligible_node_ids is None


def test_update_duty_type_sets_and_clears_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_dt2")
    dt = create_duty_type(admin_session, name="dt_update_scope", score_per_day=Decimal("1.00"))
    admin_session.commit()

    update_duty_type(
        admin_session, duty_type=dt, name=None, score_per_day=None, description=None,
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert dt.eligible_node_ids == [node.id]

    update_duty_type(
        admin_session, duty_type=dt, name=None, score_per_day=None, description=None,
        eligible_node_ids=None,
    )
    admin_session.commit()
    assert dt.eligible_node_ids is None
