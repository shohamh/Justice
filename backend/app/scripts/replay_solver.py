"""Replay a solver run from a JSON dump.

The dump is produced by GET /api/algorithm/jobs/{id}/export-inputs.

Usage (from backend/ directory):
    uv run python -m app.scripts.replay_solver path/to/solver_dump_<id>.json
    uv run python -m app.scripts.replay_solver dump.json --time-limit 120 --seed 42
    uv run python -m app.scripts.replay_solver dump.json --decomposition calendar
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date
from decimal import Decimal

from app.algorithm.types import (
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
)
from app.algorithm.solver import solve


def _load_dump(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_soldiers(raw: list[dict]) -> list[SoldierInput]:
    return [
        SoldierInput(
            id=uuid.UUID(s["id"]),
            enrolled_at=date.fromisoformat(s["enrolled_at"]),
            cumulative_score=Decimal(str(s["cumulative_score"])),
            active_days=s["active_days"],
            hierarchy_node_id=uuid.UUID(s["hierarchy_node_id"]) if s.get("hierarchy_node_id") else None,
            approved_constraint_dates=[
                (date.fromisoformat(a), date.fromisoformat(b))
                for a, b in s.get("approved_constraint_dates", [])
            ],
            exempted_duty_type_ids={uuid.UUID(e) for e in s.get("exempted_duty_type_ids", [])},
            effort_offset=s.get("effort_offset", 0),
            effort_per_milli=s.get("effort_per_milli", 0),
        )
        for s in raw
    ]


def _parse_duties(raw: list[dict]) -> list[DutyBlock]:
    return [
        DutyBlock(
            id=uuid.UUID(d["id"]),
            duty_type_id=uuid.UUID(d["duty_type_id"]),
            duty_location_id=uuid.UUID(d["duty_location_id"]),
            start_date=date.fromisoformat(d["start_date"]),
            end_date=date.fromisoformat(d["end_date"]),
            score_per_day=Decimal(str(d["score_per_day"])),
            is_reserve=d.get("is_reserve", False),
            eligible_node_ids=[uuid.UUID(n) for n in d["eligible_node_ids"]] if d.get("eligible_node_ids") else None,
        )
        for d in raw
    ]


def _parse_existing(raw: list[dict]) -> list[ExistingAssignment]:
    return [
        ExistingAssignment(
            soldier_id=uuid.UUID(e["soldier_id"]),
            duty_type_id=uuid.UUID(e["duty_type_id"]),
            start_date=date.fromisoformat(e["start_date"]),
            end_date=date.fromisoformat(e["end_date"]),
            is_reserve=e.get("is_reserve", False),
        )
        for e in raw
    ]


def _parse_settings(raw: dict, overrides: dict) -> SolverSettings:
    merged = {**raw, **overrides}
    return SolverSettings(
        T=merged.get("T", 8),
        Wt=merged.get("Wt", 14),
        R=merged.get("R", 15),
        Wr=merged.get("Wr", 28),
        alpha=Decimal(str(merged.get("alpha", 1.0))),
        time_limit_seconds=merged.get("time_limit_seconds", 60),
        seed=merged.get("seed"),
        reserve_hierarchy_weight=Decimal(str(merged.get("reserve_hierarchy_weight", 0.5))),
        effort_resolution=merged.get("effort_resolution", 1000),
        effort_range_min=merged.get("effort_range_min", 0),
        effort_range_max=merged.get("effort_range_max", 0),
        relax_r_ceiling=merged.get("relax_r_ceiling", 20),
        relax_t_ceiling=merged.get("relax_t_ceiling", 10),
        batching_enabled=merged.get("batching_enabled", True),
        batch_window_days=merged.get("batch_window_days", 28),
        batch_time_limit_seconds=merged.get("batch_time_limit_seconds", 60),
        decomposition=merged.get("decomposition", "effort_rounds"),
        round_soldier_count=merged.get("round_soldier_count", 20),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay solver from a JSON dump (export-inputs endpoint)"
    )
    parser.add_argument("dump", help="Path to solver_dump_<job_id>.json")
    parser.add_argument("--time-limit", type=int, metavar="SECS", help="Override time_limit_seconds")
    parser.add_argument("--seed", type=int, help="Override random seed")
    parser.add_argument(
        "--decomposition",
        choices=["effort_rounds", "calendar", "none"],
        help="Override decomposition strategy",
    )
    parser.add_argument("--round-count", type=int, metavar="N", help="Override round_soldier_count")
    args = parser.parse_args()

    dump = _load_dump(args.dump)

    print(f"Job:      {dump['job_id']}")
    print(f"Planning: {dump['planning_start']} → {dump['planning_end']}")
    print(f"Exported: {dump.get('exported_at', 'unknown')}")
    print(f"Input:    {len(dump['soldiers'])} soldiers, {len(dump['duties'])} duties, "
          f"{len(dump['existing_assignments'])} existing assignments")

    overrides: dict = {}
    if args.time_limit is not None:
        overrides["time_limit_seconds"] = args.time_limit
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.decomposition is not None:
        overrides["decomposition"] = args.decomposition
    if args.round_count is not None:
        overrides["round_soldier_count"] = args.round_count

    soldiers = _parse_soldiers(dump["soldiers"])
    duties = _parse_duties(dump["duties"])
    existing = _parse_existing(dump["existing_assignments"])
    settings = _parse_settings(dump["settings"], overrides)

    print(
        f"\nSettings: T={settings.T}, Wt={settings.Wt}, R={settings.R}, Wr={settings.Wr}, "
        f"time_limit={settings.time_limit_seconds}s, decomposition={settings.decomposition}"
    )
    print(
        f"          effort_range=[{settings.effort_range_min}, {settings.effort_range_max}], "
        f"resolution={settings.effort_resolution}"
    )
    if overrides:
        print(f"Overrides: {overrides}")

    print("\nSolving…")
    result = solve(soldiers, duties, existing, settings)

    assigned = len(result.assignments)
    total = len(duties)
    status_icon = "✓" if result.status == "OPTIMAL" else "~" if result.status == "FEASIBLE" else "✗"
    print(f"\n{status_icon} Status:   {result.status}")
    print(f"  Assigned: {assigned}/{total}")
    if result.objective_value is not None:
        print(f"  Objective: {result.objective_value:.6f}")
    if result.solver_metrics:
        m = result.solver_metrics
        print(f"  Wall time: {m.get('wall_time', '?'):.2f}s  "
              f"Conflicts: {m.get('conflicts', '?')}  "
              f"Branches: {m.get('branches', '?')}")
    if result.relaxed:
        print(f"  Relaxed: {result.relaxed}")

    if result.batch_results:
        print(f"\nBatch breakdown ({len(result.batch_results)} batches):")
        for br in result.batch_results:
            icon = "✓" if br.outcome == "OPTIMAL" else "~" if br.outcome == "FEASIBLE" else "✗"
            print(
                f"  {icon} [{br.batch_index}] {br.date_from}→{br.date_to}  "
                f"{br.assigned_count}/{br.duty_count} assigned  "
                f"{br.wall_time_seconds:.1f}s  {br.outcome}"
                + (f"  relaxations={br.relaxations}" if br.relaxations else "")
            )


if __name__ == "__main__":
    main()
