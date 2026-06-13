from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable, Sequence
from datetime import timedelta

from ortools.sat.python.cp_model import CpSolver, IntVar

from app.algorithm.model import (
    _block_score,
    _duty_dates,
    build_fairness_objective,
    build_model,
)
from app.algorithm.types import (
    Assignment,
    BatchResult,
    BatchShiftFill,
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

    When ``settings.batching_enabled`` the run is decomposed according to
    ``settings.decomposition``: ``"effort_rounds"`` (default) chunks soldiers into
    disjoint effort-sorted rounds per eligibility component (``_effort_round_solve``);
    ``"calendar"`` splits into chronological date-window batches (``_decomposed_solve``).
    ``"none"`` or ``batching_enabled=False`` solves the whole problem in one model.

    ``progress_cb(done, total)`` is invoked once with (0, total) before solving
    and after each batch completes, so callers can report real progress.
    """
    if settings.decomposition == "effort_rounds" and settings.batching_enabled:
        return _effort_round_solve(soldiers, duties, existing, settings, reserve_dist,
                                   cancel_event=cancel_event, progress_cb=progress_cb)
    if settings.decomposition == "calendar" and settings.batching_enabled:
        return _decomposed_solve(soldiers, duties, existing, settings, reserve_dist,
                                 cancel_event=cancel_event, progress_cb=progress_cb)
    # Unknown/``"none"`` decomposition value or batching disabled → whole solve in one model.
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


def _calendar_window_batches(
    duty_idxs_sorted: list[int], duties: Sequence[DutyBlock], batch_window_days: int
) -> list[list[int]]:
    """Group duties into non-overlapping calendar windows of batch_window_days.

    Window N covers [window_start, window_start + batch_window_days). When the
    next duty's start_date falls outside the current window, a new window opens
    anchored at that duty's start_date. This keeps duties that couple via the
    Wr density window in the same batch, reducing infeasibility-relaxation artifacts.
    """
    if not duty_idxs_sorted:
        return []
    batches: list[list[int]] = []
    window_start = duties[duty_idxs_sorted[0]].start_date
    cur: list[int] = []
    for di in duty_idxs_sorted:
        d = duties[di]
        if (d.start_date - window_start).days >= batch_window_days:
            if cur:
                batches.append(cur)
            window_start = d.start_date
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
    plan: list[tuple[int, list[int], list[int]]] = []  # (component_index, soldier_idxs, batch_duty_idxs)
    for comp_idx, (duty_idxs, soldier_idxs) in enumerate(components):
        if not soldier_idxs:
            continue
        duty_idxs = sorted(duty_idxs, key=lambda di: (duties[di].start_date, str(duties[di].id)))
        for batch in _calendar_window_batches(duty_idxs, duties, settings.batch_window_days):
            if batch:
                plan.append((comp_idx, soldier_idxs, batch))

    total = len(plan)
    if progress_cb:
        progress_cb(0, total)

    batch_settings = dataclasses.replace(
        settings, time_limit_seconds=settings.batch_time_limit_seconds
    )

    batch_results: list[BatchResult] = []
    all_assignments: list[Assignment] = []
    relaxed: list[str] = []
    carry_existing: list[ExistingAssignment] = list(existing)

    for done, (comp_idx, soldier_idxs, batch) in enumerate(plan, start=1):
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

        t0 = time.monotonic()
        res = _infeasibility_relaxation_chain(
            sub_soldiers, sub_duties, carry_existing, batch_settings, sub_rd,
            cancel_event=cancel_event,
        )
        wall_time = time.monotonic() - t0

        if res.status == "CANCELLED":
            return res
        relaxed.extend(res.relaxed)
        all_assignments.extend(res.assignments)

        # Collect batch diagnostics. Store block.id in BatchShiftFill.shift_id as a
        # temporary stand-in — the bridge replaces these with real DutyShift UUIDs.
        assigned_duty_ids = {a.duty_id for a in res.assignments}
        shifts_fill = [
            BatchShiftFill(
                shift_id=duties[di].id,
                required_count=1,
                assigned_count=1 if duties[di].id in assigned_duty_ids else 0,
            )
            for di in batch
        ]
        batch_results.append(BatchResult(
            batch_index=done - 1,
            component_index=comp_idx,
            date_from=min(duties[di].start_date for di in batch),
            date_to=max(duties[di].end_date for di in batch),
            duty_count=len(batch),
            soldier_count=len(soldier_idxs),
            assigned_count=len(res.assignments),
            unassigned_count=len(batch) - len(res.assignments),
            outcome=res.status,
            relaxations=list(res.relaxed),
            wall_time_seconds=round(wall_time, 3),
            shifts=shifts_fill,
        ))

        # Feed-forward: later batches see these as fixed (density) and as effort.
        for a in res.assignments:
            d = duty_by_id[a.duty_id]
            carry_existing.append(ExistingAssignment(
                soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                start_date=d.start_date, end_date=d.end_date,
                is_reserve=d.is_reserve,
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
        batch_results=batch_results,
    )


def _solve_soft_coverage(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None,
    cancel_event: threading.Event | None = None,
) -> SolverResult:
    """Stage 1 maximize coverage; stage 2 fix coverage and optimize fairness.

    Coverage is soft (<=1) so unplaceable duties are left unselected (deferred
    by the caller). Two-stage lexicographic on a single model avoids stacking a
    coverage tier above the 1e11 L1 weight (which risks int64 overflow).
    """
    model, x, terms = build_model(
        soldiers, duties, existing, settings, reserve_dist,
        coverage="soft", with_obj_terms=True,
    )
    covered = sum(x.values()) if x else 0
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = settings.time_limit_seconds
    seed = settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 8

    # Stage 1: maximize number of covered duties. Replaces the fairness
    # objective that build_model installed.
    model.Maximize(covered)
    if cancel_event is not None:
        threading.Thread(target=_watch_cancel, args=(solver, cancel_event), daemon=True).start()
    st1 = solver.Solve(model)
    if solver.StatusName(st1) not in ("OPTIMAL", "FEASIBLE"):
        return SolverResult(
            assignments=[], status="CANCELLED", seed=seed, relaxed=[],
        )
    best = int(round(solver.ObjectiveValue()))

    # Stage 2: pin coverage to the optimum, then optimize fairness.
    if x:
        model.Add(covered >= best)
    build_fairness_objective(model, x, duties, settings, reserve_dist, terms)
    if cancel_event is not None:
        threading.Thread(target=_watch_cancel, args=(solver, cancel_event), daemon=True).start()
    st2 = solver.Solve(model)
    if solver.StatusName(st2) not in ("OPTIMAL", "FEASIBLE"):
        return SolverResult(assignments=[], status="CANCELLED", seed=seed, relaxed=[])
    status = solver.StatusName(st2)

    assignments = [
        Assignment(duty_id=duties[di].id, soldier_id=soldiers[si].id)
        for (di, si), v in x.items()
        if solver.Value(v)
    ]
    assignments.sort(key=lambda a: a.duty_id)
    return SolverResult(assignments=assignments, status=status, seed=seed, relaxed=[])


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


def _relax_step(current: SolverSettings) -> str | None:
    """Apply one graduated density-relaxation step in place; return its label.

    R (total, incl. reserve) loosens first in hops of 2 up to relax_r_ceiling,
    then T (real only) loosens in hops of 2 up to relax_t_ceiling. Mutates
    ``current`` and returns the ``"R→k"``/``"T→k"`` label, or None when both
    ceilings are exhausted.
    """
    if current.R < current.relax_r_ceiling:
        current.R = min(current.relax_r_ceiling, current.R + 2)
        return f"R→{current.R}"
    if current.T < current.relax_t_ceiling:
        current.T = min(current.relax_t_ceiling, current.T + 2)
        return f"T→{current.T}"
    return None


def _effort_round_solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
    progress_cb: ProgressCb | None = None,
) -> SolverResult:
    """Two-phase effort-round decomposition, per connected component.

    Phase 1: chunk the component's soldiers (sorted by initial effort_offset
    ascending) into disjoint groups of ``round_soldier_count`` and cover as much
    as possible at hard BASE caps, group by group. Phase 2: bring the full
    component pool back and run graduated R/T relaxation on the residual up to
    the configured ceilings. Any duties still unassigned after Phase 2 are left
    unassigned — relaxation ceilings are an absolute bound.
    """
    # Work on copies so effort carry-forward doesn't mutate the caller's objects.
    work = [dataclasses.replace(s) for s in soldiers]
    soldier_by_id = {s.id: s for s in work}
    duty_by_id = {d.id: d for d in duties}

    # Index maps for reserve_dist remapping (global→local within any sub-problem).
    global_duty_idx: dict[object, int] = {d.id: i for i, d in enumerate(duties)}
    global_sol_idx: dict[object, int] = {s.id: i for i, s in enumerate(work)}

    base_settings = dataclasses.replace(
        settings, time_limit_seconds=settings.batch_time_limit_seconds
    )

    pairs = _eligible_pairs(work, duties)
    components = _connected_components(len(duties), len(work), pairs)

    def _remap_rd(
        sub_soldiers: Sequence[SoldierInput],
        sub_duties: Sequence[DutyBlock],
    ) -> dict[tuple[int, int], int] | None:
        """Remap global reserve_dist indices to a sub-problem's local indices."""
        if reserve_dist is None:
            return None
        out: dict[tuple[int, int], int] = {}
        for local_di, d in enumerate(sub_duties):
            gdi = global_duty_idx.get(d.id)
            if gdi is None:
                continue
            for local_si, s in enumerate(sub_soldiers):
                gsi = global_sol_idx.get(s.id)
                if gsi is None:
                    continue
                v = reserve_dist.get((gdi, gsi))
                if v is not None:
                    out[(local_di, local_si)] = v
        return out or None

    n_components = len(components)
    if progress_cb:
        progress_cb(0, n_components)

    all_assignments: list[Assignment] = []
    relaxed: list[str] = []
    # Effort/density carry-forward shared across components and rounds.
    carry: list[ExistingAssignment] = list(existing)

    for done, (duty_idxs, soldier_idxs) in enumerate(components, start=1):
        if cancel_event is not None and cancel_event.is_set():
            return SolverResult(
                assignments=[], status="CANCELLED",
                seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
                relaxed=relaxed,
            )

        if not soldier_idxs:
            # Duties with no eligible soldier — left unassigned.
            if progress_cb:
                progress_cb(done, n_components)
            continue

        full_pool = [work[si] for si in soldier_idxs]
        residual = [duties[di] for di in duty_idxs]

        def _absorb(result: SolverResult) -> None:
            for a in result.assignments:
                d = duty_by_id[a.duty_id]
                carry.append(ExistingAssignment(
                    soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                    start_date=d.start_date, end_date=d.end_date,
                    is_reserve=d.is_reserve,
                ))
                s = soldier_by_id[a.soldier_id]
                s.effort_offset += s.effort_per_milli * _block_score(d)
                all_assignments.append(a)
            covered = {a.duty_id for a in result.assignments}
            residual[:] = [d for d in residual if d.id not in covered]

        # ── Phase 1: disjoint effort-sorted rounds at hard BASE caps ──────────
        group_pool = sorted(full_pool, key=lambda s: (s.effort_offset, str(s.id)))
        rsc = max(1, settings.round_soldier_count)
        for gi in range(0, len(group_pool), rsc):
            if not residual:
                break
            group = group_pool[gi:gi + rsc]
            res = _solve_soft_coverage(
                group, residual, carry, base_settings, reserve_dist=_remap_rd(group, residual),
                cancel_event=cancel_event,
            )
            if res.status == "CANCELLED":
                return SolverResult(
                    assignments=[], status="CANCELLED", seed=res.seed, relaxed=relaxed,
                )
            _absorb(res)

        # ── Phase 2: full pool + graduated relaxation on residual ─────────────
        if residual:
            current = dataclasses.replace(base_settings)
            while residual:
                res = _solve_soft_coverage(
                    full_pool, residual, carry, current, reserve_dist=_remap_rd(full_pool, residual),
                    cancel_event=cancel_event,
                )
                if res.status == "CANCELLED":
                    return SolverResult(
                        assignments=[], status="CANCELLED", seed=res.seed, relaxed=relaxed,
                    )
                if res.assignments:
                    _absorb(res)
                    if not residual:
                        break
                label = _relax_step(current)
                if label is None:
                    break
                relaxed.append(label)

        if progress_cb:
            progress_cb(done, n_components)

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
    # hops of 2 up to relax_r_ceiling, absorbing reserve overload before real-duty
    # fairness is touched. Then T (real only) loosens up to relax_t_ceiling.
    # The invariant T <= R holds throughout.
    while True:
        solver, x, status = _solve_with_settings(soldiers, duties, existing, current, reserve_dist, cancel_event=cancel_event)
        status_name = solver.StatusName(status)

        # UNKNOWN means StopSearch() fired before a solution was found \u2014 treat as cancelled
        if status_name not in ("OPTIMAL", "FEASIBLE", "INFEASIBLE"):
            return SolverResult(assignments=[], status="CANCELLED", seed=(current.seed if current.seed is not None else DEFAULT_SOLVER_SEED), relaxed=relaxed)

        if status_name == "INFEASIBLE":
            label = _relax_step(current)
            if label is not None:
                relaxed.append(label)
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
