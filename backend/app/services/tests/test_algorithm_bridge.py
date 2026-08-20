from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings
from app.db.models import DutyLocation, HierarchyNode
from app.services.algorithm_bridge import (
    _build_node_parents,
    build_hierarchy_maps,
    load_duty_blocks_from_shifts,
    resolve_solver_settings,
    serialize_solver_inputs,
)
from app.services.duty_config import create_duty_type
from app.services.settings_loader import set_setting
from app.services.shift_quotas import set_shift_quotas
from app.services.shifts import create_shift


def test_resolve_solver_settings_uses_system_defaults(admin_session):
    set_setting(admin_session, "algorithm.max_duties_per_window", 6, actor_id=None)
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    set_setting(admin_session, "algorithm.window_t", 21, actor_id=None)
    set_setting(admin_session, "algorithm.window_r", 35, actor_id=None)
    set_setting(admin_session, "algorithm.relax_t_ceiling", 8, actor_id=None)
    set_setting(admin_session, "algorithm.relax_r_ceiling", 15, actor_id=None)
    admin_session.flush()

    s = resolve_solver_settings(admin_session, {})
    assert s.T == 6
    assert s.R == 10
    assert s.Wt == 21
    assert s.Wr == 35
    assert s.relax_t_ceiling == 8
    assert s.relax_r_ceiling == 15


def test_resolve_solver_settings_per_run_overrides_win(admin_session):
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    admin_session.flush()
    s = resolve_solver_settings(admin_session, {"T": 5, "R": 9, "Wt": 14, "Wr": 28})
    assert s.T == 5
    assert s.R == 9
    assert s.Wt == 14
    assert s.Wr == 28


def test_resolve_solver_settings_falls_back_to_hardcoded_defaults(admin_session):
    s = resolve_solver_settings(admin_session, {})
    assert s.T == 8
    assert s.R == 15
    assert s.Wt == 14
    assert s.Wr == 28
    assert s.relax_t_ceiling == 10
    assert s.relax_r_ceiling == 20


def test_resolve_solver_settings_decomposition_default(admin_session):
    s = resolve_solver_settings(admin_session, {})
    assert s.decomposition == "interleaved"
    assert s.round_soldier_count == 20
    assert s.interleaved_batch_size == 50


def test_resolve_solver_settings_decomposition_override(admin_session):
    s = resolve_solver_settings(admin_session, {"decomposition": "calendar", "round_soldier_count": 30})
    assert s.decomposition == "calendar"
    assert s.round_soldier_count == 30


def test_resolve_solver_settings_auto_relax_node_quotas_default_false(admin_session):
    s = resolve_solver_settings(admin_session, {})
    assert s.auto_relax_node_quotas is False


def test_resolve_solver_settings_auto_relax_node_quotas_per_run_override(admin_session):
    s = resolve_solver_settings(admin_session, {"auto_relax_node_quotas": True})
    assert s.auto_relax_node_quotas is True


def test_build_node_parents_maps_ids_to_immediate_parent(admin_session):
    root = HierarchyNode(level="division", name="root", parent_id=None, commander_id=None, path_ids=[])
    admin_session.add(root)
    admin_session.flush()
    root.path_ids = [root.id]

    child = HierarchyNode(level="brigade", name="child", parent_id=root.id, commander_id=None, path_ids=[])
    admin_session.add(child)
    admin_session.flush()
    child.path_ids = [root.id, child.id]
    admin_session.flush()

    hierarchy_parent, _, _, _ = build_hierarchy_maps(admin_session)
    node_parents = _build_node_parents(hierarchy_parent)

    assert node_parents[child.id] == root.id
    assert root.id not in node_parents


def test_serialize_solver_inputs_shape():
    job_id = uuid.uuid4()
    soldier_id = uuid.uuid4()
    hierarchy_node_id = uuid.uuid4()
    exempted_duty_type_id = uuid.uuid4()
    duty_id = uuid.uuid4()
    duty_type_id = uuid.uuid4()
    duty_location_id = uuid.uuid4()
    eligible_node_id = uuid.uuid4()
    shift_id = uuid.uuid4()
    existing_soldier_id = uuid.uuid4()
    existing_duty_type_id = uuid.uuid4()

    constraint_start = date(2026, 1, 5)
    constraint_end = date(2026, 1, 7)

    soldier = SoldierInput(
        id=soldier_id,
        enrolled_at=date(2024, 3, 1),
        cumulative_score=Decimal("12.5"),
        active_days=300,
        hierarchy_node_id=hierarchy_node_id,
        approved_constraint_dates=[(constraint_start, constraint_end)],
        exempted_duty_type_ids={exempted_duty_type_id},
        effort_offset=10,
        effort_per_milli=3,
    )

    duty = DutyBlock(
        id=duty_id,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 3),
        score_per_day=Decimal("2.0"),
        is_reserve=True,
        eligible_node_ids=[eligible_node_id],
    )

    existing = ExistingAssignment(
        soldier_id=existing_soldier_id,
        duty_type_id=existing_duty_type_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        is_reserve=False,
    )

    settings = SolverSettings(alpha=Decimal("1.75"), reserve_hierarchy_weight=Decimal("0.35"))

    result = serialize_solver_inputs(
        job_id=job_id,
        planning_start=date(2026, 2, 1),
        planning_end=date(2026, 2, 3),
        settings=settings,
        soldiers=[soldier],
        duties=[duty],
        existing=[existing],
        block_to_shift_map={duty.id: shift_id},
    )

    assert set(result.keys()) == {
        "job_id",
        "planning_start",
        "planning_end",
        "exported_at",
        "settings",
        "soldiers",
        "duties",
        "existing_assignments",
    }
    assert result["job_id"] == str(job_id)

    soldier_dict = result["soldiers"][0]
    assert soldier_dict["id"] == str(soldier_id)
    assert soldier_dict["enrolled_at"] == "2024-03-01"
    assert soldier_dict["cumulative_score"] == 12.5
    assert isinstance(soldier_dict["cumulative_score"], float)
    assert soldier_dict["active_days"] == 300
    assert soldier_dict["hierarchy_node_id"] == str(hierarchy_node_id)
    assert soldier_dict["approved_constraint_dates"] == [
        [constraint_start.isoformat(), constraint_end.isoformat()]
    ]
    assert soldier_dict["exempted_duty_type_ids"] == [str(exempted_duty_type_id)]
    assert soldier_dict["effort_offset"] == 10
    assert soldier_dict["effort_per_milli"] == 3

    duty_dict = result["duties"][0]
    assert duty_dict["id"] == str(duty_id)
    assert duty_dict["duty_type_id"] == str(duty_type_id)
    assert duty_dict["duty_location_id"] == str(duty_location_id)
    assert duty_dict["start_date"] == "2026-02-01"
    assert duty_dict["end_date"] == "2026-02-03"
    assert duty_dict["score_per_day"] == 2.0
    assert duty_dict["is_reserve"] is True
    assert duty_dict["eligible_node_ids"] == [str(eligible_node_id)]
    assert duty_dict["shift_id"] == str(shift_id)

    existing_dict = result["existing_assignments"][0]
    assert existing_dict["soldier_id"] == str(existing_soldier_id)
    assert existing_dict["duty_type_id"] == str(existing_duty_type_id)
    assert existing_dict["start_date"] == "2026-01-01"
    assert existing_dict["end_date"] == "2026-01-02"
    assert existing_dict["is_reserve"] is False

    assert isinstance(result["settings"]["alpha"], float)
    assert result["settings"]["alpha"] == 1.75
    assert isinstance(result["settings"]["reserve_hierarchy_weight"], float)
    assert result["settings"]["reserve_hierarchy_weight"] == 0.35


def test_serialize_solver_inputs_duty_with_no_shift_mapping():
    duty_id = uuid.uuid4()
    duty = DutyBlock(
        id=duty_id,
        duty_type_id=uuid.uuid4(),
        duty_location_id=uuid.uuid4(),
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 3),
        score_per_day=Decimal("2.0"),
    )

    result = serialize_solver_inputs(
        job_id=uuid.uuid4(),
        planning_start=date(2026, 2, 1),
        planning_end=date(2026, 2, 3),
        settings=SolverSettings(),
        soldiers=[],
        duties=[duty],
        existing=[],
        block_to_shift_map={},
    )

    assert result["duties"][0]["shift_id"] is None


def test_load_soldier_inputs_populates_path_ids(admin_session):
    from datetime import date as _date
    from app.services.algorithm_bridge import load_soldier_inputs
    from tests.helpers import create_node, create_soldier

    root = create_node(admin_session, level="division", name="div_pathids")
    child = create_node(admin_session, level="unit", name="unit_pathids", parent=root)
    soldier = create_soldier(admin_session, personal_number="pathids_1", hierarchy_node_id=child.id)
    admin_session.commit()

    inputs = load_soldier_inputs(admin_session, as_of=_date(2026, 6, 1))
    by_id = {s.id: s for s in inputs}
    assert by_id[soldier.id].path_ids == [root.id, child.id]


def test_load_soldier_inputs_unassigned_soldier_has_empty_path_ids(admin_session):
    from datetime import date as _date
    from app.services.algorithm_bridge import load_soldier_inputs
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="pathids_2")
    admin_session.commit()

    inputs = load_soldier_inputs(admin_session, as_of=_date(2026, 6, 1))
    by_id = {s.id: s for s in inputs}
    assert by_id[soldier.id].path_ids == []


def test_load_soldier_inputs_resolves_duty_location_exemptions(admin_session):
    from datetime import timedelta as _timedelta
    from app.db.models import DutyLocation, ExemptionDutyLocationMap, ExemptionType, SoldierExemption
    from app.services.algorithm_bridge import load_soldier_inputs
    from tests.helpers import create_soldier

    loc = DutyLocation(name=f"algo_loc_{uuid.uuid4().hex[:8]}")
    et = ExemptionType(name=f"algo_loc_et_{uuid.uuid4().hex[:8]}")
    admin_session.add_all([loc, et])
    admin_session.flush()
    admin_session.add(ExemptionDutyLocationMap(exemption_type_id=et.id, duty_location_id=loc.id))

    soldier = create_soldier(admin_session, personal_number=f"algo_loc_s_{uuid.uuid4().hex[:8]}")
    admin_session.add(SoldierExemption(
        soldier_id=soldier.id, exemption_type_id=et.id, start_date=date.today() - _timedelta(days=1),
    ))
    admin_session.commit()

    inputs = load_soldier_inputs(admin_session, as_of=date.today())
    soldier_input = next(s for s in inputs if s.id == soldier.id)
    assert soldier_input.exempted_duty_location_ids == {loc.id}


def test_load_duty_blocks_from_shifts_populates_node_quotas(admin_session):
    from tests.helpers import create_node

    dt = create_duty_type(admin_session, name="dt_bridge_quota", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="loc_bridge_quota")
    admin_session.add(loc)
    admin_session.flush()
    # Relative to today, not a fixed date: load_duty_blocks_from_shifts clamps
    # a shift's effective start to max(start_date, today) and skips shifts
    # entirely in the past, so a hardcoded past date here would silently
    # yield zero blocks once the calendar caught up to it.
    today = date.today()
    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=today + timedelta(days=1),
        end_date=today + timedelta(days=2),
        required_count=3,
    )
    admin_session.flush()

    node_a = create_node(admin_session, level="branch", name="ענף ברידג'")
    set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(node_a.id, 1)])
    admin_session.commit()

    blocks, block_to_shift = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    primary_blocks = [b for b in blocks if not b.is_reserve]
    assert len(primary_blocks) == 3

    quota_blocks = [b for b in primary_blocks if b.node_quotas]
    assert len(quota_blocks) == 1
    assert quota_blocks[0].node_quotas == {node_a.id: 1}

    unquota_blocks = [b for b in primary_blocks if not b.node_quotas]
    assert len(unquota_blocks) == 2
    for b in unquota_blocks:
        assert b.node_quotas is None


def test_load_soldier_inputs_filters_by_eligible_node_ids(admin_session):
    from datetime import date
    from app.services.algorithm_bridge import load_soldier_inputs
    from tests.helpers import create_node, create_soldier

    root = create_node(admin_session, level="unit", name=f"alg_root_{uuid.uuid4().hex[:8]}")
    inside = create_node(admin_session, level="unit", name=f"alg_inside_{uuid.uuid4().hex[:8]}", parent=root)
    outside = create_node(admin_session, level="unit", name=f"alg_outside_{uuid.uuid4().hex[:8]}")

    in_scope = create_soldier(admin_session, personal_number=f"alg1_{uuid.uuid4().hex[:8]}", hierarchy_node_id=inside.id)
    out_of_scope = create_soldier(admin_session, personal_number=f"alg2_{uuid.uuid4().hex[:8]}", hierarchy_node_id=outside.id)
    admin_session.commit()

    result = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1), eligible_node_ids=[root.id])
    ids = {s.id for s in result}
    assert in_scope.id in ids
    assert out_of_scope.id not in ids


def test_resolve_solver_settings_defaults_enforce_weapon_qualification_true(admin_session):
    settings = resolve_solver_settings(admin_session, {})
    assert settings.enforce_weapon_qualification is True


def test_resolve_solver_settings_reads_system_setting_default(admin_session):
    set_setting(admin_session, "weapon_qualification.enforce_eligibility", False, actor_id=None)
    admin_session.commit()
    settings = resolve_solver_settings(admin_session, {})
    assert settings.enforce_weapon_qualification is False


def test_resolve_solver_settings_per_run_override_wins(admin_session):
    set_setting(admin_session, "weapon_qualification.enforce_eligibility", True, actor_id=None)
    admin_session.commit()
    settings = resolve_solver_settings(admin_session, {"enforce_weapon_qualification": False})
    assert settings.enforce_weapon_qualification is False


def _future_ineligible_for(session, *, soldiers, duties):
    """Reproduces exactly what run_algorithm_job does after load_soldier_inputs:
    populate SoldierInput.future_ineligible_duty_block_ids from
    bulk_future_ineligible_duty_blocks. run_algorithm_job itself opens its own
    session_scope() and needs a persisted AlgorithmJob, so it isn't directly
    drivable from a test session — this composes the same two calls the job
    makes, over real DB rows."""
    from app.services.rank_eligibility_projection import bulk_future_ineligible_duty_blocks

    future_ineligible = bulk_future_ineligible_duty_blocks(
        session, soldier_ids=[s.id for s in soldiers], duties=duties,
    )
    for s in soldiers:
        s.future_ineligible_duty_block_ids = future_ineligible.get(s.id, set())
    return soldiers


def test_bridge_populates_future_ineligible_block_ids_for_projected_rank(admin_session):
    from app.services.algorithm_bridge import load_soldier_inputs
    from tests.helpers import create_soldier

    dt = create_duty_type(
        admin_session, name=f"dt_future_rank_{uuid.uuid4().hex[:6]}",
        score_per_day=Decimal("1.00"), requirements={"allowed_ranks": ["רבט"]},
    )
    loc = DutyLocation(name=f"loc_future_rank_{uuid.uuid4().hex[:6]}")
    admin_session.add(loc)
    soldier = create_soldier(admin_session, personal_number=f"fut_r_{uuid.uuid4().hex[:6]}")
    soldier.rank = "טוראי"          # never advances — no next_rank_date
    admin_session.commit()

    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1), score_per_day=Decimal("1.00"),
    )
    soldiers = load_soldier_inputs(admin_session, as_of=date(2026, 6, 1))
    _future_ineligible_for(admin_session, soldiers=soldiers, duties=[block])

    soldier_input = next(s for s in soldiers if s.id == soldier.id)
    assert block.id in soldier_input.future_ineligible_duty_block_ids


def test_bridge_populates_future_ineligible_block_ids_for_future_exemption(admin_session):
    from app.db.models import ExemptionDutyTypeMap, ExemptionType, SoldierExemption
    from app.services.algorithm_bridge import load_soldier_inputs
    from tests.helpers import create_soldier

    dt = create_duty_type(
        admin_session, name=f"dt_future_ex_{uuid.uuid4().hex[:6]}", score_per_day=Decimal("1.00"),
    )
    loc = DutyLocation(name=f"loc_future_ex_{uuid.uuid4().hex[:6]}")
    et = ExemptionType(name=f"et_future_ex_{uuid.uuid4().hex[:6]}")
    admin_session.add_all([loc, et])
    admin_session.flush()
    admin_session.add(ExemptionDutyTypeMap(exemption_type_id=et.id, duty_type_id=dt.id))
    soldier = create_soldier(admin_session, personal_number=f"fut_e_{uuid.uuid4().hex[:6]}")
    # Exemption is NOT active at the planning start — only over the block's date.
    admin_session.add(SoldierExemption(
        soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date(2026, 5, 1), end_date=date(2026, 7, 1),
    ))
    admin_session.commit()

    early_block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 1), score_per_day=Decimal("1.00"),
    )
    exempt_block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1), score_per_day=Decimal("1.00"),
    )
    soldiers = load_soldier_inputs(admin_session, as_of=date(2026, 1, 1))
    _future_ineligible_for(admin_session, soldiers=soldiers, duties=[early_block, exempt_block])

    soldier_input = next(s for s in soldiers if s.id == soldier.id)
    assert exempt_block.id in soldier_input.future_ineligible_duty_block_ids
    assert early_block.id not in soldier_input.future_ineligible_duty_block_ids
