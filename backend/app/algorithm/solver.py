from __future__ import annotations

from typing import Sequence

from ortools.sat.python.cp_model import CpSolver, IntVar

from app.algorithm.model import build_model
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverResult,
    SolverSettings,
)


def solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
) -> SolverResult:
    """Build the CP-SAT model and solve it. Returns assignments + metrics."""
    return _infeasibility_relaxation_chain(soldiers, duties, existing, settings)


def _solve_with_settings(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
) -> tuple[CpSolver, dict[tuple[int, int], IntVar], int]:
    model, x = build_model(soldiers, duties, existing, settings)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = settings.time_limit_seconds
    if settings.seed is not None:
        solver.parameters.random_seed = settings.seed
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    return solver, x, status


def _infeasibility_relaxation_chain(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
) -> SolverResult:
    current = SolverSettings(
        K=settings.K, T=settings.T, W=settings.W,
        alpha=settings.alpha, beta=settings.beta,
        time_limit_seconds=settings.time_limit_seconds,
        seed=settings.seed,
    )
    relaxed: list[str] = []
    duty_list = list(duties)
    soldier_list = list(soldiers)

    for attempt in range(5):
        solver, x, status = _solve_with_settings(soldiers, duties, existing, current)
        status_name = solver.StatusName(status)

        if status_name == "INFEASIBLE":
            if attempt < 3:
                current.K = current.K + 1
                relaxed.append(f"K\u2192{current.K}")
                continue
            elif attempt < 4:
                current.T = current.T + 1
                relaxed.append(f"T\u2192{current.T}")
                continue
            else:
                return SolverResult(
                    assignments=[], status="INFEASIBLE",
                    seed=current.seed or 0, relaxed=relaxed,
                )

        assignments: list[Assignment] = []
        for (di, si), var in x.items():
            if solver.Value(var):
                assignments.append(Assignment(
                    duty_id=duty_list[di].id,
                    soldier_id=soldier_list[si].id,
                ))

        assignments.sort(key=lambda a: a.duty_id)

        return SolverResult(
            assignments=assignments,
            status=status_name,
            objective_value=solver.ObjectiveValue() if status_name in ("OPTIMAL", "FEASIBLE") else None,
            seed=current.seed or 0,
            solver_metrics={
                "wall_time": solver.WallTime(),
                "conflicts": solver.NumConflicts(),
                "branches": solver.NumBranches(),
            },
            relaxed=relaxed,
        )

    return SolverResult(assignments=[], status="INFEASIBLE", seed=current.seed or 0, relaxed=relaxed)
