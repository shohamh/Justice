from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.models import DutyType, ExemptionDutyTypeMap, ExemptionType, Soldier, SoldierExemption, PotentialModifier
from app.services.hierarchy import create_node
from app.services.potential import PotentialModifierError, _rank_as_of, compute_potential, create_modifier, delete_modifier, list_modifiers


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
    assert result.total_soldiers == 2


def test_total_soldiers_excludes_soldiers_discharged_before_reference_date(app_session):
    node = create_node(app_session, level="team", name="Test Co Sadach", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=node.id)
    _make_soldier(app_session, node_id=node.id, left_at=date(2026, 1, 1))  # discharged before reference_date
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.total_soldiers == 1


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


def test_soldier_detail_includes_rank(app_session):
    node = create_node(app_session, level="team", name="Test Co Rank", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=node.id, rank="סמל")
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.soldiers[0].rank == "סמל"


def test_soldier_detail_rank_reflects_next_rank_date_rollover(app_session):
    node = create_node(app_session, level="team", name="Test Co Rank 2", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id, rank="טוראי")
    s.next_rank_date = date(2026, 1, 1)  # before reference_date -> rolled over
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.soldiers[0].rank == "רבט"


def test_soldier_detail_rank_reflects_chained_rollover(app_session):
    from app.services.rank_advancement import upsert_interval

    node = create_node(app_session, level="team", name="Test Co Rank 3", parent_id=None)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id, rank="טוראי")
    s.next_rank_date = date(2026, 1, 1)
    upsert_interval(app_session, track="enlisted", rank="רבט", months_to_next=1, advance_on_career_entry=False, actor_id=None)
    app_session.commit()

    # reference_date is 3 months past the first rollover -- should have
    # chained one further step (רבט -> סמל) too, not stopped at רבט.
    result = _rank_as_of(app_session, s, date(2026, 4, 1))
    assert result == "סמל"


def test_regular_exemption_excludes_soldier_and_names_it(app_session):
    node = create_node(app_session, level="team", name="Test Co 2b", parent_id=None)
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
    detail = result.soldiers[0]
    assert detail.counted is False
    assert detail.reason == "exempted"
    assert detail.exemption_names == ["פטור רפואי מלא"]


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


def test_allowed_service_types_excludes_mandatory_soldier_from_career_only_duty(app_session):
    node = create_node(app_session, level="team", name="Test Co 4a", parent_id=None)
    app_session.flush()
    dt = DutyType(
        name="שמירה", score_per_day=Decimal("1.0"),
        requirements={"allowed_service_types": ["קבע"]},
    )
    app_session.add(dt)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    s.mandatory_end_date = date(2027, 1, 1)  # after reference_date -> inferred as "חובה"
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 0
    assert result.soldiers[0].counted is False


def test_allowed_service_types_includes_mandatory_soldier_for_mandatory_only_duty(app_session):
    node = create_node(app_session, level="team", name="Test Co 4b", parent_id=None)
    app_session.flush()
    dt = DutyType(
        name="שמירה", score_per_day=Decimal("1.0"),
        requirements={"allowed_service_types": ["חובה"]},
    )
    app_session.add(dt)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    s.mandatory_end_date = date(2027, 1, 1)  # after reference_date -> inferred as "חובה"
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 1


def test_potential_rolls_up_to_parent(app_session):
    parent = create_node(app_session, level="division", name="Battalion", parent_id=None)
    app_session.flush()
    child_a = create_node(app_session, level="unit", name="Co A", parent_id=parent.id)
    child_b = create_node(app_session, level="unit", name="Co B", parent_id=parent.id)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    _make_soldier(app_session, node_id=child_a.id)
    _make_soldier(app_session, node_id=child_a.id)
    _make_soldier(app_session, node_id=child_b.id)
    app_session.commit()

    result = compute_potential(app_session, node_id=parent.id, reference_date=date(2026, 7, 3))
    assert result.raw_eligible_count == 3


def test_modifier_deep_in_subtree_rolls_up(app_session):
    parent = create_node(app_session, level="division", name="Battalion 2", parent_id=None)
    app_session.flush()
    child = create_node(app_session, level="unit", name="Co C", parent_id=parent.id)
    app_session.flush()

    app_session.add(PotentialModifier(
        hierarchy_node_id=child.id, delta=-5, reason="external duty",
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=parent.id, reference_date=date(2026, 7, 3))
    assert result.final_potential == -5


def test_create_modifier_requires_reason(app_session):
    node = create_node(app_session, level="team", name="Co D", parent_id=None)
    app_session.commit()
    try:
        create_modifier(app_session, hierarchy_node_id=node.id, delta=-10, reason="  ", start_date=date(2026, 1, 1))
        assert False, "expected PotentialModifierError"
    except PotentialModifierError as exc:
        assert "reason" in str(exc)


def test_create_and_list_modifier(app_session):
    node = create_node(app_session, level="team", name="Co E", parent_id=None)
    app_session.commit()
    m = create_modifier(
        app_session, hierarchy_node_id=node.id, delta=-60, reason="external duties not in system",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )
    app_session.commit()
    rows = list_modifiers(app_session, hierarchy_node_id=node.id)
    assert len(rows) == 1
    assert rows[0].id == m.id


def test_delete_modifier(app_session):
    node = create_node(app_session, level="team", name="Co F", parent_id=None)
    app_session.commit()
    m = create_modifier(app_session, hierarchy_node_id=node.id, delta=5, reason="temp boost", start_date=date(2026, 1, 1))
    app_session.commit()
    delete_modifier(app_session, modifier_id=m.id)
    app_session.commit()
    assert list_modifiers(app_session, hierarchy_node_id=node.id) == []


def test_export_potential_table_xlsx_returns_bytes(app_session):
    node = create_node(app_session, level="team", name="Export Co", parent_id=None)
    app_session.commit()
    from app.services.potential import export_potential_table_xlsx
    content = export_potential_table_xlsx(app_session, root_node_id=node.id, reference_date=date(2026, 7, 3))
    assert content[:2] == b"PK"  # xlsx is a zip archive


def test_discharged_soldier_reason(app_session):
    node = create_node(app_session, level="team", name="Test Co Discharged", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id, left_at=date(2026, 1, 1))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    detail = result.soldiers[0]
    assert detail.counted is False
    assert detail.reason == "discharged"


def test_partial_exemption_flags_soldier_still_counted(app_session):
    node = create_node(app_session, level="team", name="Test Co Partial", parent_id=None)
    app_session.flush()
    dt1 = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    dt2 = DutyType(name="מטבח", score_per_day=Decimal("1.0"), requirements={})
    app_session.add_all([dt1, dt2])
    app_session.flush()
    et = ExemptionType(name="פטור שמירות", is_global=False, is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    app_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt1.id))

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    detail = result.soldiers[0]
    assert detail.counted is True
    assert detail.partial_exemption_names == ["פטור שמירות"]
    assert result.raw_eligible_count == 1
    assert result.partial_exemption_count == 1


def test_fully_exempt_soldier_not_counted_as_partial(app_session):
    node = create_node(app_session, level="team", name="Test Co Partial 2", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    et = ExemptionType(name="פטור רפואי מלא 2", is_global=True, is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    detail = result.soldiers[0]
    assert detail.counted is False
    assert detail.partial_exemption_names == []
    assert result.partial_exemption_count == 0


def test_compute_potential_includes_eligible_duty_type_ids(app_session):
    node = create_node(app_session, level="team", name="Test Co DT", parent_id=None)
    app_session.flush()
    male_only = DutyType(
        name="male_only", score_per_day=Decimal("1.0"),
        requirements={"allowed_genders": ["m"]},
    )
    unrestricted = DutyType(name="any", score_per_day=Decimal("1.0"), requirements={})
    app_session.add_all([male_only, unrestricted])
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id, gender="f")
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))
    detail = result.soldiers[0]
    assert s.id == detail.soldier_id
    assert unrestricted.id in detail.eligible_duty_type_ids
    assert male_only.id not in detail.eligible_duty_type_ids


def test_compute_potential_ignores_revoked_exemption(app_session):
    from datetime import datetime, timezone

    node = create_node(app_session, level="team", name="Potential Revoke Co", parent_id=None)
    app_session.flush()
    dt = DutyType(name="שמירה-revoke-test", score_per_day=Decimal("1.0"), requirements={})
    app_session.add(dt)
    et = ExemptionType(name="פטור-revoke-potential-test", is_global=True, is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()

    s = _make_soldier(app_session, node_id=node.id)
    app_session.add(SoldierExemption(
        soldier_id=s.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), end_date=None,
        revoked_at=datetime.now(timezone.utc),
    ))
    app_session.commit()

    result = compute_potential(app_session, node_id=node.id, reference_date=date(2026, 7, 3))

    # The exemption is revoked, so it must NOT exclude the soldier from eligibility.
    assert result.raw_eligible_count == 1
    assert result.soldiers[0].counted is True
