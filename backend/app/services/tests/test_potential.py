from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.models import DutyType, ExemptionType, Soldier, SoldierExemption
from app.services.hierarchy import create_node
from app.services.potential import compute_potential


def _make_soldier(session, *, node_id, rank="טוראי", left_at=None, gender="m"):
    s = Soldier(
        personal_number=str(uuid.uuid4())[:8],
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node_id,
        rank=rank,
        gender=gender,
        left_at=left_at,
    )
    session.add(s)
    session.flush()
    return s


def test_compute_potential_counts_eligible_soldiers(app_session):
    node = create_node(app_session, level="team", name="Test Co", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=node.id)
    _make_soldier(app_session, node_id=node.id)
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))

    assert result.raw_eligible_count == 2
    assert result.final_potential == 2


def test_regular_global_exemption_excludes_soldier(app_session):
    node = create_node(app_session, level="team", name="Test Co 2", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    et = ExemptionType(name="פטור רפואי מלא", is_global=True, is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 0
    assert result.soldiers[0].counted is False


def test_commander_exemption_does_not_exclude_soldier(app_session):
    node = create_node(app_session, level="team", name="Test Co 3", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    et = ExemptionType(name="פטור פיקודי כללי", is_global=True, is_commander_exemption=True)
    app_session.add(et)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 1


def test_mitvahim_alal_ignored_for_potential(app_session):
    node = create_node(app_session, level="team", name="Test Co 4", parent_id=None)
    app_session.flush()
    dt = DutyType(
        name="שמירה", score_per_day=Decimal("1.0"),
        requirements={"requires_mitvahim": True},
    )
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=node.id)  # no last_mitvahim_date set at all
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 1
