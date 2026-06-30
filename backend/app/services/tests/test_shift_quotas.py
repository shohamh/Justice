from __future__ import annotations

import uuid
from decimal import Decimal

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type
from app.services.shift_quotas import ShiftQuotaError, get_shift_quotas, set_shift_quotas
from app.services.shifts import create_shift
from tests.helpers import create_node

import pytest
from datetime import date


def _make_shift(session, name_suffix: str, required_count: int):
    dt = create_duty_type(session, name=f"dt_quota_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_quota_{name_suffix}")
    session.add(loc)
    session.flush()
    shift = create_shift(
        session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        required_count=required_count,
    )
    session.flush()
    return shift


def test_set_quotas_within_required_count(admin_session):
    shift = _make_shift(admin_session, "1", required_count=5)
    node_a = create_node(admin_session, level="branch", name="ענף פוקוס")
    node_b = create_node(admin_session, level="branch", name="ענף אלומות")

    set_shift_quotas(admin_session, shift_id=shift.id, quotas=[
        (node_a.id, 2), (node_b.id, 3),
    ])
    admin_session.flush()

    result = get_shift_quotas(admin_session, shift_id=shift.id)
    assert {(q.hierarchy_node_id, q.count) for q in result} == {(node_a.id, 2), (node_b.id, 3)}


def test_set_quotas_over_required_count_raises(admin_session):
    shift = _make_shift(admin_session, "2", required_count=3)
    node_a = create_node(admin_session, level="branch", name="ענף פוקוס")
    node_b = create_node(admin_session, level="branch", name="ענף אלומות")

    with pytest.raises(ShiftQuotaError, match="exceeds required_count"):
        set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(node_a.id, 2), (node_b.id, 2)])


def test_set_quotas_unknown_node_raises(admin_session):
    shift = _make_shift(admin_session, "3", required_count=3)
    with pytest.raises(ShiftQuotaError, match="not found"):
        set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(uuid.uuid4(), 1)])


def test_set_quotas_replaces_existing(admin_session):
    shift = _make_shift(admin_session, "4", required_count=5)
    node_a = create_node(admin_session, level="branch", name="ענף פוקוס")
    node_b = create_node(admin_session, level="branch", name="ענף אלומות")

    set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(node_a.id, 2)])
    admin_session.flush()
    set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(node_b.id, 3)])
    admin_session.flush()

    result = get_shift_quotas(admin_session, shift_id=shift.id)
    assert {(q.hierarchy_node_id, q.count) for q in result} == {(node_b.id, 3)}
