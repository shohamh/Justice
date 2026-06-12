from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable, Sequence
from datetime import timedelta

from ortools.sat.python.cp_model import CpSolver, IntVar

from app.algorithm.model import _block_score, _duty_dates, build_model
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverResult,
    SolverSettings,
)

# Default CP-SAT random seed used whenever a caller doesn't specify one, so
# algorithm runs are reproducible by default.
DEFAULT_SOLVER_SEED = 42


def _watch_cancel(solver: CpSolver, event: threading.Event) -> None:
    """Daemon thread: calls StopSearch when the cancel event fires."""
    event.wait()
    solver.StopSearch()


ProgressCb = Callable[[int, int], None]  # (batches_done, batches_total)


def solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
    progress_cb: ProgressCb | None = None,
) -> SolverResult:
    """Build the CP-SAT model and solve it. Returns assignments + metrics.

    When ``settings.batching_enabled`` the run is decomposed into independent
    eligibility components and chronological batches, each solved on its own so
    the L1 fairness objective stays tractable (see ``_decomposed_solve``).
    Otherwise the whole problem is solved in one model.

    ``progress_cb(done, total)`` is invoked once with (0, total) before solving
    and after each batch completes, so callers can report real progress.
    """
    if settings.batching_enabled and len(duties) > settings.batch_size:
        return _decomposed_solve(
            soldiers, duties, existing, settings, reserve_dist,
            cancel_event=cancel_event, progress_cb=progress_cb,
        )
    if progress_cb:
        progress_cb(0, 1)
    result = _infeasibility_relaxation_chain(soldiers, duties, existing, settings, reserve_dist, cancel_event=cancel_event)
    if progress_cb:
        progress_cb(1, 1)
    return result


# ── Decomposition + chronological batching ────────────────────────────────────


def _eligible_pairs(
    soldiers: Sequence[SoldierInput], duties: Sequence[DutyBlock]
) -> list[tuple[int, int]]:
    """(duty_idx, soldier_idx) pairs where the soldier may take the duty.

    Mirrors build_model's eligibility filter (exemption, personal constraint,
    hierarchy node).
    """
    pairs: list[tuple[int, int]] = []
    constraint_dates: list[set] = []
    for s in soldiers:
        dates: set = set()
        for cs, ce in s.approved_constraint_dates:
            d = cs
            while d <= ce:
                dates.add(d)
                d += timedelta(days=1)
        constraint_dates.append(dates)
    for di, d in enumerate(duties):
        ddates = _duty_dates(d)
        for si, s in enumerate(soldiers):
            if d.duty_type_id in s.exempted_duty_type_ids:
                continue
            if any(t in constraint_dates[si] for t in ddates):
                continue
            if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
                if s.hierarchy_node_id not in d.eligible_node_ids:
                    continue
            pairs.append((di, si))
    return pairs


def _connected_components(
    n_duties: int, n_soldiers: int, pairs: Sequence[tuple[int, int]]
) -> list[tuple[list[int], list[int]]]:
    """Union-find over the bipartite eligibility graph.

    Returns [(duty_idxs, soldier_idxs)] for each component that has ≥1 duty.
    Duty node = di, soldier node = n_duties + si.
    """
    parent = list(range(n_duties + n_soldiers))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for di, si in pairs:
        union(di, n_duties + si)

    duty_groups: dict[int, list[int]] = {}
    soldier_groups: dict[int, list[int]] = {}
    for di in range(n_duties):
        duty_groups.setdefault(find(di), []).append(di)
    for si in range(n_soldiers):
        soldier_groups.setdefault(find(n_duties + si), []).append(si)

    components: list[tuple[list[int], list[int]]] = []
    for root, dids in duty_groups.items():
        components.append((dids, soldier_groups.get(root, [])))
    return components


def _date_batches(
    duty_idxs_sorted: list[int], duties: Sequence[DutyBlock], batch_size: int
) -> list[list[int]]:
    """Chronological batches of ~batch_size duties that never split a single date.

    Keeping a date whole avoids cross-batch no-overlap conflicts (a soldier carried
    as 'existing' from one batch can't take a same-date duty in the next).
    """
    batches: list[list[int]] = []
    cur: list[int] = []
    for di in duty_idxs_sorted:
        if cur and len(cur) >= batch_size and duties[di].start_date != duties[cur[-1]].start_date:
            batches.append(cur)
            cur = []
        cur.append(di)
    if cur:
        batches.append(cur)
    return batches


def _decomposed_solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None,
    cancel_event: threading.Event | None,
    progress_cb: ProgressCb | None = None,
) -> SolverResult:
    # Work on copies so the cross-batch effort feedback doesn't mutate the
    # caller's soldiers (the bridge still needs original effort for explanations).
    work = [dataclasses.replace(s) for s in soldiers]
    soldier_by_id = {s.id: s for s in work}
    duty_by_id = {d.id: d for d in duties}

    pairs = _eligible_pairs(work, duties)
    components = _connected_components(len(duties), len(work), pairs)

    # Pre-compute the full batch plan so we can report total progress upfront.
    plan: list[tuple[list[int], list[int]]] = []  # (soldier_idxs, batch_duty_idxs)
    for duty_idxs, soldier_idxs in components:
        if not soldier_idxs:
            continue  # duties with no eligible soldier → left unassigned (infeasible component)
        # Chronological order so duties that couple via the T/W window batch together.
        duty_idxs = sorted(duty_idxs, key=lambda di: (duties[di].start_date, str(duties[di].id)))
        for batch in _date_batches(duty_idxs, duties, settings.batch_size):
            if batch:
                plan.append((soldier_idxs, batch))

    total = len(plan)
    if progress_cb:
        progress_cb(0, total)

    batch_settings = dataclasses.replace(
        settings, time_limit_seconds=settings.batch_time_limit_seconds
    )

    all_assignments: list[Assignment] = []
    relaxed: list[str] = []
    carry_existing: list[ExistingAssignment] = list(existing)

    for done, (soldier_idxs, batch) in enumerate(plan, start=1):
        sub_soldiers = [work[si] for si in soldier_idxs]
        sub_duties = [duties[di] for di in batch]
        # Remap reserve_dist (global indices) to this sub-problem's local indices.
        sub_rd: dict[tuple[int, int], int] | None = None
        if reserve_dist is not None:
            sub_rd = {}
            for local_di, gdi in enumerate(batch):
                for i, gsi in enumerate(soldier_idxs):
                    v = reserve_dist.get((gdi, gsi))
                    if v is not None:
                        sub_rd[(local_di, i)] = v

        res = _infeasibility_relaxation_chain(
            sub_soldiers, sub_duties, carry_existing, batch_settings, sub_rd,
            cancel_event=cancel_event,
        )
        if res.status == "CANCELLED":
            return res
        relaxed.extend(res.relaxed)
        all_assignments.extend(res.assignments)

        # Feed-forward: later batches see these as fixed (density) and as effort.
        for a in res.assignments:
            d = duty_by_id[a.duty_id]
            carry_existing.append(ExistingAssignment(
                soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                start_date=d.start_date, end_date=d.end_date,
            ))
            s = soldier_by_id[a.soldier_id]
            s.effort_offset += s.effort_per_milli * _block_score(d)

        if progress_cb:
            progress_cb(done, total)

    all_assignments.sort(key=lambda a: a.duty_id)
    assigned_ids = {a.duty_id for a in all_assignments}
    status = "OPTIMAL" if len(assigned_ids) == len(duties) else "FEASIBLE"
    if not all_assignments and duties:
        status = "INFEASIBLE"
    return SolverResult(
        assignments=all_assignments,
        status=status,
        seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
        relaxed=relaxed,
    )


def _solve_with_settings(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[CpSolver, dict[tuple[int, int], IntVar], int]:
    model, x = build_model(soldiers, duties, existing, settings, reserve_dist)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = settings.time_limit_seconds
    # Always seed the solver so runs are reproducible. When the objective has
    # ties (e.g. several equally-fair assignments), an unseeded multi-worker
    # search returns a different optimum each run; a fixed seed makes the result
    # deterministic. Callers may override via settings.seed.
    solver.parameters.random_seed = settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED
    solver.parameters.num_search_workers = 8
    if cancel_event is not None:
        threading.Thread(target=_watch_cancel, args=(solver, cancel_event), daemon=True).start()
    status = solver.Solve(model)
    return solver, x, status


def _infeasibility_relaxation_chain(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
) -> SolverResult:
    # Copy so we can relax T/R without touching the caller's settings.
    current = dataclasses.replace(settings)
    relaxed: list[str] = []

    # Two-stage density relaxation. R (total, incl. reserve) loosens first in
    # hops of 2 up to 11, absorbing reserve overload before real-duty fairness
    # is touched. Then T (real only) loosens in hops of 2 up to 9. The invariant
    # T <= R holds throughout: R reaches 11 before T leaves 7.
    R_MAX = 11
    T_MAX = 9

    while True:
        solver, x, status = _solve_with_settings(soldiers, duties, existing, current, reserve_dist, cancel_event=cancel_event)
        status_name = solver.StatusName(status)

        # UNKNOWN means StopSearch() fired before a solution was found \u2014 treat as cancelled
        if status_name not in ("OPTIMAL", "FEASIBLE", "INFEASIBLE"):
            return SolverResult(assignments=[], status="CANCELLED", seed=(current.seed if current.seed is not None else DEFAULT_SOLVER_SEED), relaxed=relaxed)

        if status_name == "INFEASIBLE":
            if current.R < R_MAX:
                current.R = min(R_MAX, current.R + 2)
                relaxed.append(f"R\u2192{current.R}")
                continue
            if current.T < T_MAX:
                current.T = min(T_MAX, current.T + 2)
                relaxed.append(f"T\u2192{current.T}")
                continue
            return SolverResult(
                assignments=[], status="INFEASIBLE",
                seed=(current.seed if current.seed is not None else DEFAULT_SOLVER_SEED), relaxed=relaxed,
            )

        assignments: list[Assignment] = []
        for (di, si), var in x.items():
            if solver.Value(var):
                assignments.append(Assignment(
                    duty_id=duties[di].id,
                    soldier_id=soldiers[si].id,
                ))

        assignments.sort(key=lambda a: a.duty_id)

        return SolverResult(
            assignments=assignments,
            status=status_name,
            objective_value=solver.ObjectiveValue() if status_name in ("OPTIMAL", "FEASIBLE") else None,
            seed=(current.seed if current.seed is not None else DEFAULT_SOLVER_SEED),
            solver_metrics={
                "wall_time": solver.WallTime(),
                "conflicts": solver.NumConflicts(),
                "branches": solver.NumBranches(),
            },
            relaxed=relaxed,
        )
