from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.models import DutyType, Soldier
from app.services.hierarchy import create_node
from app.services.node_burden_share_potential import compute_node_burden_share_potential
from app.services.potential import create_modifier


def _make_soldier(session, *, node_id, rank="טוראי", gender="m"):
    s = Soldier(
        personal_number=str(uuid.uuid4())[:8],
        full_name="Test Soldier",
        password_hash="x",
        hierarchy_node_id=node_id,
        rank=rank,
        gender=gender,
    )
    session.add(s)
    session.flush()
    return s


def test_sibling_shares_sum_to_one(app_session):
    parent = create_node(app_session, level="unit", name="Gap Parent", parent_id=None)
    app_session.flush()
    child_a = create_node(app_session, level="team", name="Gap Child A", parent_id=parent.id)
    child_b = create_node(app_session, level="team", name="Gap Child B", parent_id=parent.id)
    app_session.flush()
    for _ in range(3):
        _make_soldier(app_session, node_id=child_a.id)
    for _ in range(1):
        _make_soldier(app_session, node_id=child_b.id)
    app_session.add(DutyType(name="שמירה גאפ", score_per_day=Decimal("1.0"), requirements={}))
    app_session.commit()

    results = compute_node_burden_share_potential(app_session, reference_date=date(2026, 7, 4))

    a = results[child_a.id]
    b = results[child_b.id]
    assert a.sibling_potential_share is not None and b.sibling_potential_share is not None
    assert abs((a.sibling_potential_share + b.sibling_potential_share) - 1.0) < 1e-9
    # 3 eligible soldiers in A vs 1 in B -> A should hold 3/4 of the sibling potential share
    assert abs(a.sibling_potential_share - 0.75) < 1e-9


def test_gap_is_none_when_potential_share_is_zero(app_session):
    parent = create_node(app_session, level="unit", name="Gap Parent Zero", parent_id=None)
    app_session.flush()
    child = create_node(app_session, level="team", name="Gap Child Zero", parent_id=parent.id)
    app_session.flush()
    app_session.commit()

    results = compute_node_burden_share_potential(app_session, reference_date=date(2026, 7, 4))

    r = results[child.id]
    # no soldiers anywhere under this parent -> zero total potential among siblings
    assert r.sibling_gap is None


def test_global_share_relative_to_top_level_roots(app_session):
    root_a = create_node(app_session, level="corps", name="Gap Root A", parent_id=None)
    root_b = create_node(app_session, level="corps", name="Gap Root B", parent_id=None)
    app_session.flush()
    for _ in range(2):
        _make_soldier(app_session, node_id=root_a.id)
    for _ in range(2):
        _make_soldier(app_session, node_id=root_b.id)
    app_session.add(DutyType(name="שמירה גלובלי", score_per_day=Decimal("1.0"), requirements={}))
    app_session.commit()

    results = compute_node_burden_share_potential(app_session, reference_date=date(2026, 7, 4))

    a = results[root_a.id]
    b = results[root_b.id]
    assert a.global_potential_share is not None
    assert abs(a.global_potential_share - 0.5) < 1e-6
    assert abs(b.global_potential_share - 0.5) < 1e-6


def test_negative_final_potential_is_clamped_to_zero_in_shares(app_session):
    parent = create_node(app_session, level="unit", name="Gap Parent Negative", parent_id=None)
    app_session.flush()
    child_neg = create_node(app_session, level="team", name="Gap Child Negative", parent_id=parent.id)
    child_pos = create_node(app_session, level="team", name="Gap Child Positive", parent_id=parent.id)
    app_session.flush()
    # 1 eligible soldier in each child -> raw_eligible_count of 1 apiece before modifiers.
    _make_soldier(app_session, node_id=child_neg.id)
    _make_soldier(app_session, node_id=child_pos.id)
    app_session.add(DutyType(name="שמירה שלילי", score_per_day=Decimal("1.0"), requirements={}))
    # Drive child_neg's final_potential negative with a large negative admin modifier.
    create_modifier(
        app_session,
        hierarchy_node_id=child_neg.id,
        delta=-100,
        reason="test: force negative potential",
        start_date=date(2026, 1, 1),
    )
    app_session.commit()

    results = compute_node_burden_share_potential(app_session, reference_date=date(2026, 7, 4))

    neg = results[child_neg.id]
    pos = results[child_pos.id]
    assert neg.final_potential < 0  # raw value is stored unclamped
    # clamped share must be exactly 0.0, never negative or None
    assert neg.sibling_potential_share == 0.0
    # the positive sibling should get the full 100% of the share, as if the
    # negative-potential sibling contributed zero (not a negative amount) to
    # the denominator.
    assert pos.sibling_potential_share is not None
    assert abs(pos.sibling_potential_share - 1.0) < 1e-9
