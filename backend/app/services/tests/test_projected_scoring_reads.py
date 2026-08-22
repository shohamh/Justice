from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.db.models import (
    DutyAssignment,
    ScoreProjectionDirtyBucket,
    DutyLocation,
    DutyType,
    ExemptionType,
    ScoreProjectionQuarterTotal,
    SoldierExemption,
    SoldierQuarterScoreProjection,
    SoldierScoreProjection,
)
from app.services import commander_dashboard, effort_score, score_projection, scoring
from app.services.effort_score import compute_effort_breakdown
from app.services.score_projection import backfill_score_projection
from app.services.tests.test_score_projection import _seed_projection_scenario
from app.services.settings_loader import set_setting
from tests.helpers import create_node, create_soldier



def _completed_backfill(session):
    """Drive the quarter-granular backfill until fully complete."""
    from app.services.score_projection import backfill_score_projection

    state = backfill_score_projection(session)
    while not state.backfill_complete:
        state = backfill_score_projection(session)
    return state


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.000001"))
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _canonical_breakdown(breakdown) -> dict[str, Any]:
    return _canonical(
        {
            "quarters": [
                {
                    "quarter_start": quarter.quarter_start,
                    "quarter_end": quarter.quarter_end,
                    "quarter_label": quarter.quarter_label,
                    "soldier_score": quarter.soldier_score,
                    "unit_score": quarter.unit_score,
                    "active_frac": quarter.active_frac,
                    "share": quarter.share,
                    "weighted_share": quarter.weighted_share,
                    "is_partial": quarter.is_partial,
                    "adjustment_delta": quarter.adjustment_delta,
                }
                for quarter in breakdown.quarters
            ],
            "effort_score": breakdown.effort_score,
            "A_i": breakdown.A_i,
            "W_i": breakdown.W_i,
        }
    )


def _build_projected_scenario(session):
    scenario = _seed_projection_scenario(session)
    admin = create_soldier(
        session,
        personal_number="projected-read-admin",
        role="admin",
        full_name="Projected Read Admin",
    )
    return scenario, admin


def _fail_if_expands_duty_days(*_args, **_kwargs):
    raise AssertionError("normal projected scoring read expanded duty days")


def _fail_if_enumerates_canonical_buckets(*_args, **_kwargs):
    raise AssertionError("normal projected scoring read enumerated canonical buckets")


def _forbid_normal_projection_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    original_effective_rows = score_projection._effective_duty_day_rows

    def fail_unbounded_projection_expansion(*args, **kwargs):
        if "assignment_ids" in kwargs:
            return original_effective_rows(*args, **kwargs)
        return _fail_if_expands_duty_days(*args, **kwargs)

    monkeypatch.setattr(score_projection, "_effective_duty_day_rows", fail_unbounded_projection_expansion)
    monkeypatch.setattr(score_projection, "project_all_buckets", _fail_if_enumerates_canonical_buckets)


def test_transparency_rows_match_legacy_from_projection_without_expanding_duty_days(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    scenario, admin = _build_projected_scenario(admin_session)
    legacy = scoring.transparency_rows(admin_session, viewer=admin)
    _completed_backfill(admin_session)
    admin_session.flush()

    _forbid_normal_projection_expansion(monkeypatch)

    projected = scoring.transparency_rows(admin_session, viewer=admin)

    assert projected["rows"]
    assert [set(row) for row in projected["rows"]] == [set(row) for row in legacy["rows"]]
    assert _canonical(projected) == _canonical(legacy)
    primary = next(row for row in projected["rows"] if row["soldier_id"] == scenario["primary"].id)
    assert primary["shift_count"] == 2
    assert primary["cumulative_score"] == Decimal("8.700000")


def test_fairness_components_use_projected_effort_without_calling_transparency_rows(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    _scenario, admin = _build_projected_scenario(admin_session)
    legacy = scoring.fairness_components(admin_session, viewer=admin)
    _completed_backfill(admin_session)
    admin_session.flush()

    def fail_transparency(*_args, **_kwargs):
        raise AssertionError("fairness must not call transparency_rows")

    monkeypatch.setattr(scoring, "transparency_rows", fail_transparency)
    _forbid_normal_projection_expansion(monkeypatch)

    projected = scoring.fairness_components(admin_session, viewer=admin)

    assert _canonical(projected) == _canonical(legacy)


def test_effort_breakdown_matches_legacy_from_projection_and_keeps_preview_in_memory(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    scenario, _admin = _build_projected_scenario(admin_session)
    soldier = scenario["primary"]
    legacy = compute_effort_breakdown(
        admin_session,
        soldier=soldier,
        planning_start=scenario["planning_start"],
        planning_end=scenario["planning_start"],
        reset_date=scenario["reset_date"],
        extra_adj_delta=Decimal("3.25"),
        extra_adj_date=date(2026, 7, 20),
    )
    _completed_backfill(admin_session)
    admin_session.flush()

    monkeypatch.setattr(effort_score, "effective_duty_days", _fail_if_expands_duty_days)
    _forbid_normal_projection_expansion(monkeypatch)

    projected = compute_effort_breakdown(
        admin_session,
        soldier=soldier,
        planning_start=scenario["planning_start"],
        planning_end=scenario["planning_start"],
        reset_date=scenario["reset_date"],
        extra_adj_delta=Decimal("3.25"),
        extra_adj_date=date(2026, 7, 20),
    )

    assert _canonical_breakdown(projected) == _canonical_breakdown(legacy)
    q3 = next(quarter for quarter in projected.quarters if quarter.quarter_start == scenario["q3"])
    assert q3.adjustment_delta == Decimal("8.250000")


def test_transparency_rebuilds_missing_projection_bucket_before_serving_projected_read(
    admin_session,
):
    scenario, admin = _build_projected_scenario(admin_session)
    legacy = scoring.transparency_rows(admin_session, viewer=admin)
    _completed_backfill(admin_session)
    admin_session.flush()

    admin_session.execute(
        delete(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == scenario["primary"].id,
            SoldierQuarterScoreProjection.quarter_start == scenario["q3"],
        )
    )
    # Out-of-band deletion is not healed on the read path under the marker
    # contract; an interrupted writer would have left a dirty marker, so mark
    # the bucket the way the writer would.
    existing_marker = admin_session.execute(
        select(ScoreProjectionDirtyBucket).where(
            ScoreProjectionDirtyBucket.soldier_id == scenario["primary"].id,
            ScoreProjectionDirtyBucket.quarter_start == scenario["q3"],
        )
    ).scalar_one_or_none()
    if existing_marker is None:
        admin_session.add(
            ScoreProjectionDirtyBucket(
                soldier_id=scenario["primary"].id,
                quarter_start=scenario["q3"],
                status="dirty",
            )
        )
    else:
        existing_marker.status = "dirty"
    admin_session.flush()

    projected = scoring.transparency_rows(admin_session, viewer=admin)

    rebuilt_rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == scenario["primary"].id,
            SoldierQuarterScoreProjection.quarter_start == scenario["q3"],
        )
    ).scalars().all()
    assert rebuilt_rows
    assert _canonical(projected) == _canonical(legacy)


def test_transparency_rebuilds_missing_soldier_total_before_projected_read(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    scenario, admin = _build_projected_scenario(admin_session)
    legacy = scoring.transparency_rows(admin_session, viewer=admin)
    _completed_backfill(admin_session)
    admin_session.flush()

    admin_session.execute(
        delete(SoldierScoreProjection).where(
            SoldierScoreProjection.soldier_id == scenario["primary"].id,
        )
    )
    admin_session.flush()
    _forbid_normal_projection_expansion(monkeypatch)

    projected = scoring.transparency_rows(admin_session, viewer=admin)

    rebuilt_total = admin_session.get(SoldierScoreProjection, scenario["primary"].id)
    primary = next(row for row in projected["rows"] if row["soldier_id"] == scenario["primary"].id)
    assert rebuilt_total is not None
    assert rebuilt_total.cumulative_score == Decimal("8.700000")
    assert primary["cumulative_score"] == Decimal("8.700000")
    assert _canonical(projected) == _canonical(legacy)


def test_effort_breakdown_self_heals_missing_quarter_total(
    admin_session,
):
    scenario, _admin = _build_projected_scenario(admin_session)
    hidden = create_soldier(
        admin_session,
        personal_number="projected-hidden-future",
        full_name="Projected Hidden Future",
    )
    admin_session.add(
        DutyAssignment(
            soldier_id=hidden.id,
            duty_type_id=scenario["cross_quarter"].duty_type_id,
            duty_location_id=scenario["cross_quarter"].duty_location_id,
            start_date=date(2026, 10, 10),
            end_date=date(2026, 10, 12),
            status="published",
        )
    )
    admin_session.flush()
    soldier = scenario["primary"]
    legacy = compute_effort_breakdown(
        admin_session,
        soldier=soldier,
        planning_start=scenario["planning_start"],
        planning_end=scenario["planning_start"],
        reset_date=scenario["reset_date"],
    )
    _completed_backfill(admin_session)
    admin_session.flush()

    admin_session.execute(
        delete(ScoreProjectionQuarterTotal).where(
            ScoreProjectionQuarterTotal.quarter_start == date(2026, 10, 1),
        )
    )
    admin_session.flush()

    projected = compute_effort_breakdown(
        admin_session,
        soldier=soldier,
        planning_start=scenario["planning_start"],
        planning_end=scenario["planning_start"],
        reset_date=scenario["reset_date"],
    )

    rebuilt_total = admin_session.get(ScoreProjectionQuarterTotal, date(2026, 10, 1))
    assert rebuilt_total is not None
    assert rebuilt_total.total_score == Decimal("2.000000")
    assert _canonical_breakdown(projected) == _canonical_breakdown(legacy)


def test_effort_breakdown_serves_from_projection_when_partition_row_goes_missing(
    admin_session,
):
    # Read-path contract: with a clean marker table the stored quarter total is
    # trusted even if a partition row disappears out-of-band — the periodic
    # revalidation worker is what detects and repairs that divergence.
    scenario, _admin = _build_projected_scenario(admin_session)
    hidden = create_soldier(
        admin_session,
        personal_number="projected-hidden-row-missing",
        full_name="Projected Hidden Row Missing",
    )
    admin_session.add(
        DutyAssignment(
            soldier_id=hidden.id,
            duty_type_id=scenario["cross_quarter"].duty_type_id,
            duty_location_id=scenario["cross_quarter"].duty_location_id,
            start_date=date(2026, 10, 10),
            end_date=date(2026, 10, 12),
            status="published",
        )
    )
    admin_session.flush()
    soldier = scenario["primary"]
    legacy = compute_effort_breakdown(
        admin_session,
        soldier=soldier,
        planning_start=scenario["planning_start"],
        planning_end=scenario["planning_start"],
        reset_date=scenario["reset_date"],
    )
    _completed_backfill(admin_session)
    admin_session.flush()

    q4_total_before = admin_session.get(ScoreProjectionQuarterTotal, date(2026, 10, 1))
    assert q4_total_before is not None
    assert q4_total_before.total_score == Decimal("2.000000")
    admin_session.execute(
        delete(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == hidden.id,
            SoldierQuarterScoreProjection.quarter_start == date(2026, 10, 1),
        )
    )
    admin_session.flush()

    projected = compute_effort_breakdown(
        admin_session,
        soldier=soldier,
        planning_start=scenario["planning_start"],
        planning_end=scenario["planning_start"],
        reset_date=scenario["reset_date"],
    )

    # The stale stored total is untouched by the read; revalidation owns repair.
    q4_total_after = admin_session.get(ScoreProjectionQuarterTotal, date(2026, 10, 1))
    assert q4_total_after.total_score == Decimal("2.000000")
    assert _canonical_breakdown(projected) == _canonical_breakdown(legacy)


def test_transparency_repairs_marked_divergent_bucket_without_expansion(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    # Read-path contract: a bucket whose marker implicates it (dirty or
    # divergent) is rebuilt from canonical rows before serving; unmarked
    # corruption is the revalidation worker's job, not the read's.
    scenario, admin = _build_projected_scenario(admin_session)
    legacy = scoring.transparency_rows(admin_session, viewer=admin)
    _completed_backfill(admin_session)
    admin_session.flush()

    stale_row = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == scenario["primary"].id,
            SoldierQuarterScoreProjection.quarter_start == scenario["q3"],
            SoldierQuarterScoreProjection.duty_type_id.is_not(None),
        )
    ).scalar_one()
    stale_row.duty_score = Decimal("99.000000")
    stale_row.source_fingerprint = {"stale": True}
    dirty_marker = admin_session.execute(
        select(ScoreProjectionDirtyBucket).where(
            ScoreProjectionDirtyBucket.soldier_id == scenario["primary"].id,
            ScoreProjectionDirtyBucket.quarter_start == scenario["q3"],
        )
    ).scalar_one_or_none()
    if dirty_marker is None:
        dirty_marker = ScoreProjectionDirtyBucket(
            soldier_id=scenario["primary"].id,
            quarter_start=scenario["q3"],
            status="dirty",
        )
        admin_session.add(dirty_marker)
    else:
        dirty_marker.status = "dirty"
    admin_session.flush()
    _forbid_normal_projection_expansion(monkeypatch)

    projected = scoring.transparency_rows(admin_session, viewer=admin)

    repaired_rows = admin_session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == scenario["primary"].id,
            SoldierQuarterScoreProjection.quarter_start == scenario["q3"],
            SoldierQuarterScoreProjection.duty_type_id.is_not(None),
        )
    ).scalars().all()
    assert repaired_rows
    assert all(row.source_fingerprint != {"stale": True} for row in repaired_rows)
    assert _canonical(projected) == _canonical(legacy)


def test_projected_transparency_matches_legacy_for_scoped_redacted_non_admin(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    set_setting(admin_session, "transparency.min_visible_level", "every_soldier", actor_id=None)
    in_scope = create_node(admin_session, level="division", name="projected-in-scope")
    out_scope = create_node(admin_session, level="division", name="projected-out-scope")
    viewer = create_soldier(
        admin_session,
        personal_number="projected-dm-redact",
        role="duty_manager",
        hierarchy_node_id=in_scope.id,
    )
    visible = create_soldier(
        admin_session,
        personal_number="projected-visible-redact",
        hierarchy_node_id=in_scope.id,
    )
    redacted = create_soldier(
        admin_session,
        personal_number="projected-hidden-redact",
        hierarchy_node_id=out_scope.id,
    )
    exemption_type = ExemptionType(name="projected-redacted-global", is_global=True)
    admin_session.add(exemption_type)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(
            soldier_id=redacted.id,
            exemption_type_id=exemption_type.id,
            start_date=date.today(),
        )
    )
    admin_session.flush()

    scenario = _seed_projection_scenario(admin_session)
    scenario["primary"].hierarchy_node_id = in_scope.id
    scenario["replacement"].hierarchy_node_id = out_scope.id
    admin_session.flush()
    legacy = scoring.transparency_rows(admin_session, viewer=viewer)
    _completed_backfill(admin_session)
    admin_session.flush()
    _forbid_normal_projection_expansion(monkeypatch)

    projected = scoring.transparency_rows(admin_session, viewer=viewer)

    redacted_row = next(row for row in projected["rows"] if row["soldier_id"] == redacted.id)
    visible_row = next(row for row in projected["rows"] if row["soldier_id"] == visible.id)
    assert redacted_row["exemptions_visible"] is False
    assert redacted_row["exemptions_display"] == "חסוי"
    assert redacted_row["has_global_exemption"] is True
    assert visible_row["exemptions_visible"] is True
    assert _canonical(projected) == _canonical(legacy)


def test_projected_transparency_scale_read_does_not_expand_projection_history(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    scenario, admin = _build_projected_scenario(admin_session)
    for idx in range(18):
        soldier = create_soldier(
            admin_session,
            personal_number=f"projected-scale-{idx:02d}",
            full_name=f"Projected Scale {idx:02d}",
        )
        admin_session.add(
            DutyAssignment(
                soldier_id=soldier.id,
                duty_type_id=scenario["cross_quarter"].duty_type_id,
                duty_location_id=scenario["cross_quarter"].duty_location_id,
                start_date=date(2025, 1 + (idx % 12), 1),
                end_date=date(2025, 1 + (idx % 12), 3),
                status="published",
            )
        )
    admin_session.flush()
    legacy = scoring.transparency_rows(admin_session, viewer=admin)
    _completed_backfill(admin_session)
    admin_session.flush()
    _forbid_normal_projection_expansion(monkeypatch)

    projected = scoring.transparency_rows(admin_session, viewer=admin)

    assert _canonical(projected) == _canonical(legacy)


def test_backfill_covers_empty_effort_history_quarters_so_reads_serve_from_projections(
    admin_session,
):
    # No fairness.reset_date setting is written here, so reads derive their
    # required quarters from the two-years-back default — including calendar
    # quarters with zero assignments. A completed backfill must leave a
    # quarter-total row for every one of them or every projected read silently
    # falls back to legacy.
    _scenario, admin = _build_projected_scenario(admin_session)
    _completed_backfill(admin_session)
    admin_session.flush()
    set_setting(
        admin_session,
        score_projection.SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
        True,
        actor_id=None,
    )
    admin_session.flush()

    assert scoring._try_projected_transparency_rows(admin_session) is not None


def test_dashboard_summary_uses_projected_scores_without_expanding_history(
    admin_session, monkeypatch: pytest.MonkeyPatch
):
    node = create_node(admin_session, level="division", name="projected-dashboard-node")
    soldier = create_soldier(
        admin_session,
        personal_number="projected-dashboard-soldier",
        hierarchy_node_id=node.id,
    )
    duty_type = DutyType(name="projected-dashboard-duty", score_per_day=Decimal("2.50"))
    duty_location = DutyLocation(name="projected-dashboard-location")
    admin_session.add_all([duty_type, duty_location])
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=duty_type.id,
            duty_location_id=duty_location.id,
            start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 12),
            status="published",
        )
    )
    admin_session.flush()
    legacy = commander_dashboard.summary_cards(admin_session, subtree_ids=[node.id])
    set_setting(
        admin_session,
        score_projection.SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY,
        True,
        actor_id=None,
    )
    _completed_backfill(admin_session)
    admin_session.flush()

    _forbid_normal_projection_expansion(monkeypatch)

    projected = commander_dashboard.summary_cards(admin_session, subtree_ids=[node.id])

    assert projected == legacy
