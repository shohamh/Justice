from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable, Sequence
from datetime import timedelta

from ortools.sat.python.cp_model import CpModel, CpSolver, CpSolverSolutionCallback, IntVar

from app.algorithm.model import (
    _block_score,
    _duty_dates,
    apply_tiebreak_objective,
    build_fairness_objective,
    build_model,
)
from app.algorithm.saturation import analyze_saturation
from app.algorithm.types import (
    Assignment,
    BatchResult,
    BatchShiftFill,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverResult,
    SolverSettings,
    node_in_scope,
)

# Default CP-SAT random seed used whenever a caller doesn't specify one, so
# algorithm runs are reproducible by default.
DEFAULT_SOLVER_SEED = 42

# Stop a solve early once no IMPROVING solution has been found for this many
# seconds, instead of always exhausting the full time budget. The fairness
# objective is highly symmetric whenever multiple soldiers are interchangeable
# (same eligibility/effort profile), so CP-SAT typically finds a near-optimal
# assignment in well under a second but then spends the *entire* remaining
# time limit failing to prove no better one exists — burning 30-60s on
# problems with a handful of duties. Once the search stalls this long, further
# time is overwhelmingly likely to be spent proving optimality, not finding a
# better assignment, so cutting it short trades a negligible amount of
# fairness-optimality for a large, reliable speedup.
#
# Set to 15s (was 5s): a finer-grained L1 objective gives CP-SAT more distinct
# improvement steps to find, so very short stall windows can cut off small
# single-batch components (< 100 duties) before they reach optimal fairness
# (eligible soldiers receiving 0 duties). 15s resolves this without meaningfully
# increasing runtime on large batches that stall late anyway.
STALL_SECONDS = 15.0


def _watch_cancel(solver: CpSolver, event: threading.Event) -> None:
    """Daemon thread: calls StopSearch when the cancel event fires."""
    event.wait()
    solver.StopSearch()


class _StallTracker(CpSolverSolutionCallback):
    """Records the wall-clock time of the most recent improving solution."""

    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()
        self.last_improvement = time.monotonic()
        self.has_solution = False

    def on_solution_callback(self) -> None:
        with self.lock:
            self.has_solution = True
            self.last_improvement = time.monotonic()


def _watch_stall(
    solver: CpSolver, tracker: _StallTracker, stall_seconds: float, stop_event: threading.Event
) -> None:
    """Daemon thread: calls StopSearch once no solution has improved for stall_seconds."""
    while not stop_event.is_set():
        stop_event.wait(0.25)
        with tracker.lock:
            if not tracker.has_solution:
                continue
            idle = time.monotonic() - tracker.last_improvement
        if idle > stall_seconds:
            solver.StopSearch()
            return


def _solve_with_stall_guard(
    solver: CpSolver, model: CpModel, cancel_event: threading.Event | None
) -> int:
    """Solve, stopping early on cancellation or once the search stalls (see STALL_SECONDS)."""
    tracker = _StallTracker()
    stop_event = threading.Event()
    threading.Thread(
        target=_watch_stall, args=(solver, tracker, STALL_SECONDS, stop_event), daemon=True
    ).start()
    if cancel_event is not None:
        threading.Thread(target=_watch_cancel, args=(solver, cancel_event), daemon=True).start()
    try:
        return solver.Solve(model, tracker)
    finally:
        stop_event.set()


ProgressCb = Callable[[int, int], None]  # (duties_done, duties_total)


def solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
    progress_cb: ProgressCb | None = None,
    swap_progress_cb: "Callable[[], None] | None" = None,
) -> SolverResult:
    """Build the CP-SAT model and solve it. Returns assignments + metrics.

    When ``settings.batching_enabled`` the run is decomposed according to
    ``settings.decomposition``: ``"effort_rounds"`` (default) chunks soldiers into
    disjoint effort-sorted rounds per eligibility component (``_effort_round_solve``);
    ``"calendar"`` splits into chronological date-window batches (``_decomposed_solve``).
    ``"none"`` or ``batching_enabled=False`` solves the whole problem in one model.

    ``progress_cb(done, total)`` is invoked once with (0, total) before solving
    and after each batch completes. Both values are duty counts, so larger batches
    cause proportionally more progress-bar movement.

    ``swap_progress_cb()`` is called (no arguments) just before the post-solve
    swap pass begins, so the UI can show a distinct "balancing loads…" label.
    """
    if settings.decomposition == "interleaved" and settings.batching_enabled:
        result = _interleaved_solve(soldiers, duties, existing, settings, reserve_dist,
                                    cancel_event=cancel_event, progress_cb=progress_cb)
    elif settings.decomposition == "effort_rounds" and settings.batching_enabled:
        result = _effort_round_solve(soldiers, duties, existing, settings, reserve_dist,
                                     cancel_event=cancel_event, progress_cb=progress_cb)
    elif settings.decomposition == "calendar" and settings.batching_enabled:
        result = _decomposed_solve(soldiers, duties, existing, settings, reserve_dist,
                                   cancel_event=cancel_event, progress_cb=progress_cb)
    else:
        # Unknown/``"none"`` decomposition value or batching disabled → whole solve in one model.
        total_duties = len(duties)
        if progress_cb:
            progress_cb(0, total_duties)
        result = _infeasibility_relaxation_chain(soldiers, duties, existing, settings, reserve_dist, cancel_event=cancel_event)
        if progress_cb:
            progress_cb(total_duties, total_duties)

    if result.status in ("OPTIMAL", "FEASIBLE") and result.assignments:
        if swap_progress_cb:
            swap_progress_cb()
        swapped = _swap_pass(soldiers, duties, existing, result.assignments, settings)
        result = dataclasses.replace(result, assignments=swapped)
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
            if not node_in_scope(d.eligible_node_ids, s.path_ids):
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


def _interleaved_duty_batches(
    duty_idxs: list[int],
    duties: Sequence[DutyBlock],
    target_batch_size: int,
) -> list[list[int]]:
    """Sort duties by (start_date, score_per_day desc, duty_type_id) then deal
    round-robin into N = ceil(total / target_batch_size) batches so each batch
    gets a representative mix of dates, scores, and types rather than a single
    contiguous date slice.
    """
    if not duty_idxs:
        return []
    sorted_idxs = sorted(
        duty_idxs,
        key=lambda di: (
            duties[di].start_date,
            -float(duties[di].score_per_day),
            str(duties[di].duty_type_id),
        ),
    )
    n = max(1, (len(sorted_idxs) + target_batch_size - 1) // target_batch_size)
    batches: list[list[int]] = [[] for _ in range(n)]
    for i, di in enumerate(sorted_idxs):
        batches[i % n].append(di)
    return [b for b in batches if b]


def _interleaved_solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None,
    cancel_event: threading.Event | None,
    progress_cb: ProgressCb | None = None,
) -> SolverResult:
    """Duty-interleaved decomposition.

    Duties are sorted by date/score/type then dealt round-robin into N batches,
    so each batch gets a representative mix across the planning window. All
    soldiers compete for every batch — unlike effort_rounds, no soldier is
    disadvantaged by group placement. Between batches, effort offsets and density
    state are carried forward, so soldiers who accumulate duties early are
    naturally deprioritised in later batches by the fairness objective.

    N = ceil(total_duties / settings.interleaved_batch_size).
    """
    work = [dataclasses.replace(s) for s in soldiers]
    soldier_by_id = {s.id: s for s in work}
    duty_by_id = {d.id: d for d in duties}

    pairs = _eligible_pairs(work, duties)
    components = _connected_components(len(duties), len(work), pairs)

    plan: list[tuple[int, list[int], list[int]]] = []
    for comp_idx, (duty_idxs, soldier_idxs) in enumerate(components):
        if not soldier_idxs:
            continue
        for batch in _interleaved_duty_batches(
            list(duty_idxs), duties, settings.interleaved_batch_size
        ):
            plan.append((comp_idx, soldier_idxs, batch))

    total_duties = sum(len(batch) for _, _, batch in plan)
    duties_done = 0
    if progress_cb:
        progress_cb(0, total_duties)

    batch_settings = dataclasses.replace(
        settings, time_limit_seconds=settings.batch_time_limit_seconds
    )

    batch_results: list[BatchResult] = []
    all_assignments: list[Assignment] = []
    relaxed: list[str] = []
    carry_existing: list[ExistingAssignment] = list(existing)

    for done, (comp_idx, soldier_idxs, batch) in enumerate(plan, start=1):
        if cancel_event is not None and cancel_event.is_set():
            # Batches already completed are verified solutions — keep them
            # instead of discarding a long run's work just because the last
            # batch didn't make the cutoff.
            return SolverResult(
                assignments=list(all_assignments), status="CANCELLED",
                seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
                relaxed=relaxed, batch_results=batch_results,
            )

        sub_soldiers = [work[si] for si in soldier_idxs]
        sub_duties = [duties[di] for di in batch]

        sub_rd: dict[tuple[int, int], int] | None = None
        if reserve_dist is not None:
            sub_rd = {}
            for local_di, gdi in enumerate(batch):
                for local_si, gsi in enumerate(soldier_idxs):
                    v = reserve_dist.get((gdi, gsi))
                    if v is not None:
                        sub_rd[(local_di, local_si)] = v

        t0 = time.monotonic()
        res = _infeasibility_relaxation_chain(
            sub_soldiers, sub_duties, carry_existing, batch_settings, sub_rd,
            cancel_event=cancel_event,
        )
        if res.status == "INFEASIBLE":
            # Hard-coverage model proved infeasible: some duties in this batch
            # have no eligible soldier (e.g. oversubscribed shift). Fall back to
            # soft coverage so the assignable duties are still handled.
            res = _solve_soft_coverage(
                sub_soldiers, sub_duties, carry_existing, batch_settings, sub_rd,
                cancel_event=cancel_event,
            )
        wall_time = time.monotonic() - t0

        if res.status == "CANCELLED":
            # The in-flight batch didn't finish, but prior batches did — keep them.
            return SolverResult(
                assignments=list(all_assignments), status="CANCELLED",
                seed=res.seed, relaxed=relaxed, batch_results=batch_results,
            )
        relaxed.extend(res.relaxed)
        all_assignments.extend(res.assignments)

        assigned_duty_ids = {a.duty_id for a in res.assignments}
        unassigned = [duties[di] for di in batch if duties[di].id not in assigned_duty_ids]
        saturation_clusters = (
            analyze_saturation(unassigned, sub_soldiers, all_assignments, carry_existing, duty_by_id)
            if unassigned else []
        )

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
            shifts=[
                BatchShiftFill(
                    shift_id=duties[di].id,
                    required_count=1,
                    assigned_count=1 if duties[di].id in assigned_duty_ids else 0,
                )
                for di in batch
            ],
            saturation_clusters=saturation_clusters,
        ))

        for a in res.assignments:
            d = duty_by_id[a.duty_id]
            carry_existing.append(ExistingAssignment(
                soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                start_date=d.start_date, end_date=d.end_date,
                is_reserve=d.is_reserve,
            ))
            s = soldier_by_id[a.soldier_id]
            s.effort_offset += s.effort_per_milli * _block_score(d)

        duties_done += len(batch)
        if progress_cb:
            progress_cb(duties_done, total_duties)

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

    total_duties = sum(len(batch) for _, _, batch in plan)
    duties_done = 0
    if progress_cb:
        progress_cb(0, total_duties)

    batch_settings = dataclasses.replace(
        settings, time_limit_seconds=settings.batch_time_limit_seconds
    )

    batch_results: list[BatchResult] = []
    all_assignments: list[Assignment] = []
    relaxed: list[str] = []
    carry_existing: list[ExistingAssignment] = list(existing)

    for done, (comp_idx, soldier_idxs, batch) in enumerate(plan, start=1):
        if cancel_event is not None and cancel_event.is_set():
            # Batches already completed are verified solutions — keep them
            # instead of discarding a long run's work just because the last
            # batch didn't make the cutoff.
            return SolverResult(
                assignments=list(all_assignments), status="CANCELLED",
                seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
                relaxed=relaxed, batch_results=batch_results,
            )

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
            # The in-flight batch didn't finish, but prior batches did — keep them.
            return SolverResult(
                assignments=list(all_assignments), status="CANCELLED",
                seed=res.seed, relaxed=relaxed, batch_results=batch_results,
            )
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

        duties_done += len(batch)
        if progress_cb:
            progress_cb(duties_done, total_duties)

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
    # num_search_workers=1: parallel workers introduce non-determinism because
    # whichever worker wins the race depends on CPU scheduling, not the seed.
    # Single-threaded + fixed seed = fully reproducible results across runs.
    solver.parameters.num_search_workers = settings.num_workers

    # Stage 1: maximize number of covered duties. Replaces the fairness
    # objective that build_model installed.
    model.Maximize(covered)
    st1 = _solve_with_stall_guard(solver, model, cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        return SolverResult(assignments=[], status="CANCELLED", seed=seed, relaxed=[])
    if solver.StatusName(st1) not in ("OPTIMAL", "FEASIBLE"):
        # No coverage found this attempt (timeout/UNKNOWN, not a real cancel).
        # Let the caller defer the residual instead of aborting the whole run.
        return SolverResult(assignments=[], status="FEASIBLE", seed=seed, relaxed=[])
    best = int(round(solver.ObjectiveValue()))

    # Capture stage-1 assignment now: stage 2 re-solves the same solver and
    # will overwrite these variable values.
    stage1_assignments = [
        Assignment(duty_id=duties[di].id, soldier_id=soldiers[si].id)
        for (di, si), v in x.items()
        if solver.Value(v)
    ]

    # Stage 2: pin coverage to the optimum, then optimize fairness.
    if x:
        model.Add(covered >= best)
    build_fairness_objective(model, x, duties, settings, reserve_dist, terms)
    st2 = _solve_with_stall_guard(solver, model, cancel_event)
    if cancel_event is not None and cancel_event.is_set():
        return SolverResult(assignments=[], status="CANCELLED", seed=seed, relaxed=[])
    if solver.StatusName(st2) in ("OPTIMAL", "FEASIBLE"):
        # Stage 2 found a fairer assignment at the same coverage.
        assignments = [
            Assignment(duty_id=duties[di].id, soldier_id=soldiers[si].id)
            for (di, si), v in x.items()
            if solver.Value(v)
        ]
    else:
        # Stage 2 timed out / UNKNOWN (not cancelled): keep stage-1 coverage.
        assignments = stage1_assignments
    assignments.sort(key=lambda a: a.duty_id)
    return SolverResult(assignments=assignments, status="FEASIBLE", seed=seed, relaxed=[])


def _solve_with_settings(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[CpSolver, dict[tuple[int, int], IntVar], int]:
    model, x, terms = build_model(
        soldiers, duties, existing, settings, reserve_dist, with_obj_terms=True
    )
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = settings.time_limit_seconds
    # Fixed seed + single worker = deterministic results. random_seed alone is
    # not sufficient: parallel workers race each other and whichever wins depends
    # on CPU scheduling, not the seed. Callers may override seed via settings.seed.
    solver.parameters.random_seed = settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED
    solver.parameters.num_search_workers = settings.num_workers
    status = _solve_with_stall_guard(solver, model, cancel_event)

    if settings.tiebreak_mode == "off" or not terms.dev_terms:
        return solver, x, status
    if solver.StatusName(status) not in ("OPTIMAL", "FEASIBLE"):
        return solver, x, status
    if cancel_event is not None and cancel_event.is_set():
        return solver, x, status

    # Lexicographic stage 2: pin the L1 value just proven, hint with stage 1's
    # assignment (it's already feasible and L1-optimal, so stage 2 only needs
    # to search among ties), then re-solve with a tie-break objective and a
    # separate, shorter time budget. A SEPARATE solver instance is used so
    # that if stage 2 fails to find anything within budget, `solver`'s
    # already-valid stage-1 values are untouched and safe to fall back to —
    # reusing one solver object (as the existing soft-coverage two-stage solve
    # does) would leave Value() reflecting stage 2's failed attempt instead.
    achieved_l1 = sum(solver.Value(d) for d in terms.dev_terms)
    stage1_values = {key: solver.Value(var) for key, var in x.items()}
    for key, var in x.items():
        model.AddHint(var, stage1_values[key])
    apply_tiebreak_objective(model, x, duties, settings, reserve_dist, terms, achieved_l1)

    solver2 = CpSolver()
    solver2.parameters.max_time_in_seconds = settings.tiebreak_time_limit_seconds
    solver2.parameters.random_seed = solver.parameters.random_seed
    solver2.parameters.num_search_workers = settings.num_workers
    status2 = _solve_with_stall_guard(solver2, model, cancel_event)
    if solver2.StatusName(status2) in ("OPTIMAL", "FEASIBLE"):
        return solver2, x, status2
    # Stage 2 found nothing usable within budget (or got cancelled) — fall
    # back to stage 1's untouched, already-feasible solver/status.
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


def _ladder_positions(settings: SolverSettings) -> list[tuple[list[str], SolverSettings]]:
    """Cumulative relaxation steps from `settings`' base R/T up to its ceilings.

    Reuses `_relax_step` so labels/order exactly match the existing graduated
    ladder (R first in hops of 2 to relax_r_ceiling, then T to relax_t_ceiling).
    Returns [(cumulative_labels, settings_at_that_position), ...]. Position 0
    (the unrelaxed base) is NOT included — callers try that separately first,
    since it's the cheap/common case and needs no ladder at all.
    """
    positions: list[tuple[list[str], SolverSettings]] = []
    current = dataclasses.replace(settings)
    labels: list[str] = []
    while True:
        label = _relax_step(current)
        if label is None:
            break
        labels = labels + [label]
        positions.append((labels, dataclasses.replace(current)))
    return positions


RemapRdFn = Callable[[Sequence[SoldierInput], Sequence[DutyBlock]], dict[tuple[int, int], int] | None]


def _solve_component_once(
    full_pool: Sequence[SoldierInput],
    component_duties: Sequence[DutyBlock],
    carry: Sequence[ExistingAssignment],
    settings: SolverSettings,
    remap_rd: RemapRdFn,
    cancel_event: threading.Event | None,
) -> SolverResult:
    """One complete attempt to cover `component_duties` at `settings`' R/T.

    Phase 0: whole-component hard `==1` solve (cheap path when fully coverable).
    Phase 1: disjoint effort-sorted rounds at the same R/T (no relaxation).
    Phase 2: one soft-coverage pass over whatever's still unassigned — also no
    relaxation here; trying a *higher* R/T is the caller's job (see
    `_search_relaxation_ladder`), which calls this function again from scratch.

    Pure: does not mutate `full_pool` or `carry`. Returns assignments
    referencing the original duty/soldier ids, scoped to this attempt only.
    """
    pool = [dataclasses.replace(s) for s in full_pool]
    soldier_by_id = {s.id: s for s in pool}
    duty_by_id = {d.id: d for d in component_duties}
    local_carry = list(carry)
    residual = list(component_duties)
    assignments: list[Assignment] = []
    seed = settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED

    def _absorb_local(result: SolverResult) -> None:
        for a in result.assignments:
            d = duty_by_id[a.duty_id]
            local_carry.append(ExistingAssignment(
                soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                start_date=d.start_date, end_date=d.end_date, is_reserve=d.is_reserve,
            ))
            s = soldier_by_id[a.soldier_id]
            s.effort_offset += s.effort_per_milli * _block_score(d)
            assignments.append(a)
        covered = {a.duty_id for a in result.assignments}
        residual[:] = [d for d in residual if d.id not in covered]

    # ── Phase 0: single hard-coverage solve of the WHOLE component ─────────
    solver0, x0, st0 = _solve_with_settings(
        pool, residual, local_carry, settings, reserve_dist=remap_rd(pool, residual),
        cancel_event=cancel_event,
    )
    if cancel_event is not None and cancel_event.is_set():
        return SolverResult(assignments=[], status="CANCELLED", seed=seed, relaxed=[])
    if solver0.StatusName(st0) in ("OPTIMAL", "FEASIBLE"):
        phase0 = [
            Assignment(duty_id=residual[di].id, soldier_id=pool[si].id)
            for (di, si), v in x0.items() if solver0.Value(v)
        ]
        _absorb_local(SolverResult(assignments=phase0, status=solver0.StatusName(st0), seed=seed, relaxed=[]))
        return SolverResult(assignments=assignments, status="OPTIMAL", seed=seed, relaxed=[])

    # ── Phase 1: disjoint effort-sorted rounds at this attempt's R/T ───────
    base_settings = dataclasses.replace(settings, time_limit_seconds=settings.batch_time_limit_seconds)
    # Tiebreak equal-effort soldiers by a seeded hash, not UUID string order.
    # UUID alphabetical ordering systematically disadvantages late-alphabet UUIDs
    # (e.g. fb… ends up in the last group and gets leftover duties after earlier
    # groups have claimed the only types they're eligible for).
    group_pool = sorted(pool, key=lambda s: (s.effort_offset, hash((seed, s.id))))
    rsc = max(1, settings.round_soldier_count)
    for gi in range(0, len(group_pool), rsc):
        if not residual:
            break
        group = group_pool[gi:gi + rsc]
        res = _solve_soft_coverage(
            group, residual, local_carry, base_settings, reserve_dist=remap_rd(group, residual),
            cancel_event=cancel_event,
        )
        if res.status == "CANCELLED":
            return SolverResult(assignments=[], status="CANCELLED", seed=res.seed, relaxed=[])
        _absorb_local(res)

    # ── Phase 2: full pool, one soft-coverage pass over the leftover ───────
    if residual:
        res = _solve_soft_coverage(
            pool, residual, local_carry, base_settings, reserve_dist=remap_rd(pool, residual),
            cancel_event=cancel_event,
        )
        if res.status == "CANCELLED":
            return SolverResult(assignments=[], status="CANCELLED", seed=res.seed, relaxed=[])
        if res.assignments:
            _absorb_local(res)

    if not assignments:
        status = "INFEASIBLE" if component_duties else "OPTIMAL"
    elif residual:
        status = "FEASIBLE"
    else:
        status = "OPTIMAL"
    return SolverResult(assignments=assignments, status=status, seed=seed, relaxed=[])


def _probe_with_retry(
    full_pool: Sequence[SoldierInput],
    component_duties: Sequence[DutyBlock],
    carry: Sequence[ExistingAssignment],
    settings: SolverSettings,
    remap_rd: RemapRdFn,
    cancel_event: threading.Event | None,
) -> SolverResult:
    """Probe at `settings`' R/T; if it falls short of full coverage, retry once
    with doubled time budgets before accepting the shortfall. This guards
    against wall-clock jitter near a time limit producing a false "can't be
    covered" verdict for this ladder position (don't accept 1-duty noise).
    """
    result = _solve_component_once(full_pool, component_duties, carry, settings, remap_rd, cancel_event)
    if result.status == "CANCELLED" or len(result.assignments) == len(component_duties):
        return result
    extended = dataclasses.replace(
        settings,
        time_limit_seconds=settings.time_limit_seconds * 2,
        batch_time_limit_seconds=settings.batch_time_limit_seconds * 2,
    )
    retry = _solve_component_once(full_pool, component_duties, carry, extended, remap_rd, cancel_event)
    if retry.status == "CANCELLED":
        return retry
    return retry if len(retry.assignments) > len(result.assignments) else result


def _search_relaxation_ladder(
    full_pool: Sequence[SoldierInput],
    component_duties: Sequence[DutyBlock],
    carry: Sequence[ExistingAssignment],
    settings: SolverSettings,
    remap_rd: RemapRdFn,
    cancel_event: threading.Event | None,
) -> tuple[SolverResult, list[str]]:
    """Binary-search the graduated R/T relaxation ladder for the lowest position
    that fully covers `component_duties`, doing a full Phase0+1+2 restart per
    probe (not a residual patch — see `_solve_component_once`). Each probe gets
    an extended-time retry (see `_probe_with_retry`) before its result is
    trusted. Returns (best_result, relax_labels_used); `best_result` never
    regresses to a worse attempt even while searching for a cheaper position.
    """
    def better(a: SolverResult, b: SolverResult) -> SolverResult:
        total = len(component_duties)
        if len(a.assignments) == total:
            return a
        if len(b.assignments) == total:
            return b
        return a if len(a.assignments) >= len(b.assignments) else b

    base_result = _probe_with_retry(full_pool, component_duties, carry, settings, remap_rd, cancel_event)
    if base_result.status == "CANCELLED":
        return base_result, []
    best = base_result
    if len(best.assignments) == len(component_duties):
        return best, []

    ladder = _ladder_positions(settings)
    if not ladder:
        return best, []

    top_labels, top_settings = ladder[-1]
    top_result = _probe_with_retry(full_pool, component_duties, carry, top_settings, remap_rd, cancel_event)
    if top_result.status == "CANCELLED":
        return top_result, []
    best = better(best, top_result)
    if len(top_result.assignments) < len(component_duties):
        # Proven (after retry) shortfall even at the ceiling — searching the
        # middle of the ladder can only do worse than the ceiling did.
        return best, top_labels

    # Ceiling fully covers — binary-search [0, len(ladder)-2] for a cheaper position.
    chosen_labels, chosen_result = top_labels, top_result
    lo, hi = 0, len(ladder) - 2
    while lo <= hi:
        mid = (lo + hi) // 2
        labels, mid_settings = ladder[mid]
        mid_result = _probe_with_retry(full_pool, component_duties, carry, mid_settings, remap_rd, cancel_event)
        if mid_result.status == "CANCELLED":
            return mid_result, []
        best = better(best, mid_result)
        if len(mid_result.assignments) == len(component_duties):
            chosen_labels, chosen_result = labels, mid_result
            hi = mid - 1
        else:
            lo = mid + 1
    return chosen_result, chosen_labels


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

    total_duties = sum(len(duty_idxs) for duty_idxs, _ in components)
    duties_done = 0
    if progress_cb:
        progress_cb(0, total_duties)

    all_assignments: list[Assignment] = []
    relaxed: list[str] = []
    batch_results: list[BatchResult] = []
    # Effort/density carry-forward shared across components and rounds.
    carry: list[ExistingAssignment] = list(existing)

    for done, (duty_idxs, soldier_idxs) in enumerate(components, start=1):
        if cancel_event is not None and cancel_event.is_set():
            # Components already solved are verified solutions — keep them.
            return SolverResult(
                assignments=list(all_assignments), status="CANCELLED",
                seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
                relaxed=relaxed,
                batch_results=batch_results,
            )

        component_duties = [duties[di] for di in duty_idxs]

        if not soldier_idxs:
            # Duties with no eligible soldier — left unassigned.
            if component_duties:
                batch_results.append(BatchResult(
                    batch_index=len(batch_results),
                    component_index=done - 1,
                    date_from=min(d.start_date for d in component_duties),
                    date_to=max(d.end_date for d in component_duties),
                    duty_count=len(component_duties),
                    soldier_count=0,
                    assigned_count=0,
                    unassigned_count=len(component_duties),
                    outcome="INFEASIBLE",
                    relaxations=[],
                    wall_time_seconds=0.0,
                    shifts=[BatchShiftFill(shift_id=d.id, required_count=1, assigned_count=0) for d in component_duties],
                ))
            duties_done += len(duty_idxs)
            if progress_cb:
                progress_cb(duties_done, total_duties)
            continue

        t0 = time.monotonic()
        full_pool = [work[si] for si in soldier_idxs]

        component_result, component_relaxed = _search_relaxation_ladder(
            full_pool, component_duties, carry, settings, _remap_rd, cancel_event,
        )
        if component_result.status == "CANCELLED":
            # The in-flight component didn't finish, but prior ones did — keep them.
            return SolverResult(
                assignments=list(all_assignments), status="CANCELLED",
                seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
                relaxed=relaxed,
                batch_results=batch_results,
            )

        assigned_ids_here = {a.duty_id for a in component_result.assignments}
        for a in component_result.assignments:
            d = duty_by_id[a.duty_id]
            carry.append(ExistingAssignment(
                soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                start_date=d.start_date, end_date=d.end_date, is_reserve=d.is_reserve,
            ))
            s = soldier_by_id[a.soldier_id]
            s.effort_offset += s.effort_per_milli * _block_score(d)
            all_assignments.append(a)

        assigned_here = len(component_result.assignments)
        total_here = len(component_duties)
        if assigned_here == 0 and total_here > 0:
            comp_outcome = "INFEASIBLE"
        elif assigned_here < total_here:
            comp_outcome = "FEASIBLE"
        else:
            comp_outcome = "OPTIMAL"
        still_unassigned = [d for d in component_duties if d.id not in assigned_ids_here]
        saturation_clusters = (
            analyze_saturation(still_unassigned, full_pool, all_assignments, carry, duty_by_id)
            if still_unassigned else []
        )
        batch_results.append(BatchResult(
            batch_index=len(batch_results),
            component_index=done - 1,
            date_from=min(d.start_date for d in component_duties),
            date_to=max(d.end_date for d in component_duties),
            duty_count=total_here,
            soldier_count=len(full_pool),
            assigned_count=assigned_here,
            unassigned_count=total_here - assigned_here,
            outcome=comp_outcome,
            relaxations=component_relaxed,
            wall_time_seconds=round(time.monotonic() - t0, 3),
            shifts=[
                BatchShiftFill(shift_id=d.id, required_count=1, assigned_count=1 if d.id in assigned_ids_here else 0)
                for d in component_duties
            ],
            saturation_clusters=saturation_clusters,
        ))
        relaxed.extend(component_relaxed)

        duties_done += len(duty_idxs)
        if progress_cb:
            progress_cb(duties_done, total_duties)

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


def _swap_pass(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    assignments: list[Assignment],
    settings: SolverSettings,
) -> list[Assignment]:
    """Greedy post-solve fairness improvement via first-improving duty transfers.

    Iteratively moves one duty from a high-effort donor to a low-effort recipient
    whenever the transfer passes all constraint checks and strictly reduces the
    population L1 distance from mean effort.

    Constraints checked:
      1. Eligibility — same rules as the solver (exemptions, personal constraints,
         hierarchy node scope).
      2. No-overlap — recipient has no existing duty on any of the duty's calendar
         dates.
      3. Density caps — T (non-reserve per Wt-day window) and R (all per Wr-day
         window). The transferred duty counts as 1 per overlapping window, matching
         the solver's convention for new duties.

    Optimisations:
      - First-improving swap: stops on the first valid improving transfer found.
      - Donors sorted by effort desc, recipients by effort asc.
      - Duties sorted by block_score desc per donor (big moves first).
      - Precomputed block_scores, duty date frozensets, eligibility sets.
      - Incremental effort tracking — no full recompute per iteration.
      - Capped at 3 × n_soldiers iterations.
    """
    import bisect as _bisect

    if len(assignments) < 2 or len(soldiers) < 2:
        return assignments

    duty_by_id = {d.id: d for d in duties}
    soldier_by_id = {s.id: s for s in soldiers}

    # Precompute duty metadata
    block_scores: dict = {d.id: _block_score(d) for d in duties}
    duty_ddates: dict = {}
    duty_start: dict = {}
    duty_last: dict = {}
    for d in duties:
        dd = _duty_dates(d)
        if dd:
            duty_ddates[d.id] = frozenset(dd)
            duty_start[d.id] = dd[0]
            duty_last[d.id] = dd[-1]
        else:
            duty_ddates[d.id] = frozenset()
            duty_start[d.id] = d.start_date
            duty_last[d.id] = d.start_date

    # Expand personal constraint dates per soldier
    soldier_constraint_dates: dict = {}
    for s in soldiers:
        dates: set = set()
        for cs, ce in s.approved_constraint_dates:
            dt = cs
            while dt <= ce:
                dates.add(dt)
                dt += timedelta(days=1)
        soldier_constraint_dates[s.id] = dates

    # eligible_for[duty_id] = set of soldier_ids that can take this duty
    eligible_for: dict = {}
    for d in duties:
        ddates_frozen = duty_ddates[d.id]
        elig: set = set()
        for s in soldiers:
            if d.duty_type_id in s.exempted_duty_type_ids:
                continue
            if ddates_frozen & soldier_constraint_dates[s.id]:
                continue
            if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
                if s.hierarchy_node_id not in d.eligible_node_ids:
                    continue
            elig.add(s.id)
        eligible_for[d.id] = elig

    # Mutable assignment maps
    assigned_to: dict = {a.duty_id: a.soldier_id for a in assignments}
    soldier_duties: dict = {s.id: set() for s in soldiers}
    for a in assignments:
        soldier_duties[a.soldier_id].add(a.duty_id)

    # Build per-soldier date sets from existing assignments + current solver assignments
    def _build_date_sets(sid):
        all_d: list = []
        real_d: list = []
        for ea in existing:
            if ea.soldier_id != sid:
                continue
            dt = ea.start_date
            while dt < ea.end_date:
                all_d.append(dt)
                if not ea.is_reserve:
                    real_d.append(dt)
                dt += timedelta(days=1)
        for did in soldier_duties.get(sid, set()):
            d = duty_by_id[did]
            for dt in _duty_dates(d):
                all_d.append(dt)
                if not d.is_reserve:
                    real_d.append(dt)
        return sorted(set(all_d)), sorted(set(real_d))

    all_sorted: dict = {}
    real_sorted: dict = {}
    all_set: dict = {}
    for s in soldiers:
        a, r = _build_date_sets(s.id)
        all_sorted[s.id] = a
        real_sorted[s.id] = r
        all_set[s.id] = set(a)

    def _count_in(lst, ws, we):
        return _bisect.bisect_right(lst, we) - _bisect.bisect_left(lst, ws)

    def _can_receive(sid, duty_id) -> bool:
        ddates_frozen = duty_ddates[duty_id]
        if not ddates_frozen:
            return True
        # Cheapest check first: calendar-day overlap
        if ddates_frozen & all_set[sid]:
            return False
        duty = duty_by_id[duty_id]
        d_start = duty_start[duty_id]
        d_last = duty_last[duty_id]
        # T cap: non-reserve duty-days per Wt-day window
        if not duty.is_reserve:
            ws = d_start - timedelta(days=settings.Wt - 1)
            while ws <= d_last:
                we = ws + timedelta(days=settings.Wt - 1)
                if _count_in(real_sorted[sid], ws, we) + 1 > settings.T:
                    return False
                ws += timedelta(days=1)
        # R cap: all duty-days per Wr-day window
        ws = d_start - timedelta(days=settings.Wr - 1)
        while ws <= d_last:
            we = ws + timedelta(days=settings.Wr - 1)
            if _count_in(all_sorted[sid], ws, we) + 1 > settings.R:
                return False
            ws += timedelta(days=1)
        return True

    # Initial effort state (incremental tracking)
    efforts: dict = {}
    total_effort = 0
    for s in soldiers:
        e = s.effort_offset
        for did in soldier_duties.get(s.id, set()):
            e += s.effort_per_milli * block_scores[did]
        efforts[s.id] = e
        total_effort += e
    n_soldiers = len(soldiers)

    # First-improving greedy loop
    max_iters = 3 * n_soldiers
    for _ in range(max_iters):
        mean_e = total_effort / n_soldiers
        donors = sorted(
            ((sid, eff) for sid, eff in efforts.items() if eff > mean_e),
            key=lambda x: -x[1],
        )
        if not donors:
            break

        found = False
        for from_sid, eff_a in donors:
            if found:
                break
            pm_a = soldier_by_id[from_sid].effort_per_milli
            for duty_id in sorted(soldier_duties[from_sid], key=lambda d: -block_scores[d]):
                if found:
                    break
                score = block_scores[duty_id]
                eff_a_after = eff_a - pm_a * score
                candidates = sorted(
                    (sid for sid in eligible_for[duty_id]
                     if sid != from_sid and efforts[sid] < eff_a),
                    key=lambda sid: efforts[sid],
                )
                for to_sid in candidates:
                    eff_b = efforts[to_sid]
                    if not _can_receive(to_sid, duty_id):
                        continue
                    pm_b = soldier_by_id[to_sid].effort_per_milli
                    eff_b_after = eff_b + pm_b * score
                    delta = (
                        abs(eff_a - mean_e) + abs(eff_b - mean_e)
                        - abs(eff_a_after - mean_e) - abs(eff_b_after - mean_e)
                    )
                    if delta <= 0:
                        continue
                    # Apply transfer
                    duty = duty_by_id[duty_id]
                    ddates = _duty_dates(duty)
                    assigned_to[duty_id] = to_sid
                    soldier_duties[from_sid].discard(duty_id)
                    soldier_duties[to_sid].add(duty_id)
                    removed = set(ddates)
                    all_set[from_sid] -= removed
                    all_sorted[from_sid] = sorted(all_set[from_sid])
                    if not duty.is_reserve:
                        real_sorted[from_sid] = sorted(set(real_sorted[from_sid]) - removed)
                    all_set[to_sid].update(ddates)
                    for dt in ddates:
                        _bisect.insort(all_sorted[to_sid], dt)
                        if not duty.is_reserve:
                            _bisect.insort(real_sorted[to_sid], dt)
                    efforts[from_sid] = eff_a_after
                    efforts[to_sid] = eff_b_after
                    total_effort += (pm_b - pm_a) * score
                    found = True
                    break
        if not found:
            break

    return [Assignment(duty_id=did, soldier_id=sid) for did, sid in assigned_to.items()]
