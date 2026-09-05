from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

# Scale factor for converting Decimal effort scores to CP-SAT integers.
# Lives here (the pure, dependency-free types module) so both the solver
# (app.algorithm.model) and the effort service (app.services.effort_score)
# can share it without the solver importing any DB code.
EFFORT_SCALE = 1_000_000_000  # 10^9


def node_in_scope(scope_node_ids: list[uuid.UUID] | None, soldier_path_ids: list[uuid.UUID]) -> bool:
    """True if a soldier is within an eligibility scope.

    `scope_node_ids` is None for "unrestricted" (everyone matches). Otherwise a
    soldier matches if any scoped node is itself or an ancestor of it —
    `soldier_path_ids` is the materialized root-to-self path (see
    HierarchyNode.path_ids), so this is a plain set-intersection subtree check.
    A soldier with no hierarchy node (empty path_ids) never matches a set scope.
    """
    if scope_node_ids is None:
        return True
    return any(n in soldier_path_ids for n in scope_node_ids)


@dataclass
class SoldierInput:
    """A soldier eligible for duty assignment."""
    id: uuid.UUID
    enrolled_at: date
    cumulative_score: Decimal
    active_days: int
    hierarchy_node_id: uuid.UUID | None = None
    unit_join_date: date | None = None
    path_ids: list[uuid.UUID] = field(default_factory=list)
    approved_constraint_dates: list[tuple[date, date]] = field(default_factory=list)
    exempted_duty_type_ids: set[uuid.UUID] = field(default_factory=set)
    exempted_duty_location_ids: set[uuid.UUID] = field(default_factory=set)
    # Duty-block ids (not duty-type ids, since eligibility is date-dependent — see
    # services/weapon_eligibility.py) this soldier is NOT weapon-qualified for as of
    # that block's start_date. Populated by algorithm_bridge via bulk_ineligible_duty_blocks
    # after both soldiers and duties are loaded; empty by default for existing callers.
    weapon_ineligible_duty_block_ids: set[uuid.UUID] = field(default_factory=set)
    # Duty-block ids this soldier will NOT be eligible for as of that
    # block's own start_date — covers projected rank, service-type/career,
    # mitvahim/alal recency, driving-license expiry, active exemptions, and
    # departure. Populated by algorithm_bridge via
    # bulk_future_ineligible_duty_blocks, mirroring
    # weapon_ineligible_duty_block_ids above. Empty by default for existing
    # callers/tests/fixtures. Unlike weapon qualification there is no
    # enforcement toggle — none of these factors are optional.
    future_ineligible_duty_block_ids: set[uuid.UUID] = field(default_factory=set)
    # Effort-based fairness fields (set by algorithm_bridge after loading duty blocks)
    effort_offset: int = 0      # int(effort_score × EFFORT_SCALE) — historical quarterly share
    effort_per_milli: int = 0   # int(C_over_D / unit_score_milli × EFFORT_SCALE) — per-milli contribution


@dataclass
class DutyBlock:
    """A duty block (shift) to be assigned to a soldier."""
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    score_per_day: Decimal
    is_reserve: bool = False
    eligible_node_ids: list[uuid.UUID] | None = None
    start_time: str = "00:00"
    end_time: str = "23:59"
    # Exact per-node soldier counts required for this shift's slots. Slots not
    # covered by any entry are unconstrained. Keys are hierarchy_node_id; the
    # constraint matches any soldier whose path_ids contains that node (i.e.
    # the node itself or any descendant), same semantics as eligible_node_ids.
    node_quotas: dict[uuid.UUID, int] | None = None
    # Hours of rest required after this duty ends before the same soldier can
    # start another. 0 = no rest requirement (default, safe for existing callers).
    rest_hours: int = 0
    # Minimum range-qualification tier required to take this block (laser/live/alal),
    # or None if this duty type doesn't require a weapon. Populated by algorithm_bridge
    # from DutyType.required_range_type; consumed by services/weapon_eligibility.py and
    # the solver's eligibility pre-filter (see solver.py _eligible_pairs / build_model).
    required_range_type: str | None = None
    # Raw duty-type requirements used by shared eligibility diagnostics. Kept
    # optional so existing pure solver fixtures remain backward-compatible.
    requirements: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExistingAssignment:
    """An already-published assignment for min_gap continuity."""
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date
    is_reserve: bool = False
    # Rest-window fields (all default to "no constraint" for existing callers).
    # rest_effective_end_date/time already account for an early dismissal —
    # see backend/app/services/rest.py:effective_assignment_end.
    rest_hours: int = 0
    rest_effective_end_date: date | None = None
    rest_effective_end_time: str = "23:59"


@dataclass
class SolverSettings:
    """CP-SAT solver configuration.

    T: non-reserve duty-day cap per Wt rolling window
    Wt: rolling window length (days) for the T (non-reserve) cap
    R: total duty-day cap per Wr rolling window (incl. reserve); invariant T <= R
    Wr: rolling window length (days) for the R (all-duties) cap
    alpha: score-preference weight (higher = stronger preference for low-score soldiers)
    """
    T: int = 8
    Wt: int = 14
    R: int = 15
    Wr: int = 28
    alpha: Decimal = Decimal("1.0")
    time_limit_seconds: int = 60
    seed: int | None = None
    reserve_hierarchy_weight: Decimal = Decimal("0.5")
    # Fairness L1 in count-space: auto-range maps [effort_range_min, effort_range_max]
    # to [0, effort_resolution] so all resolution ticks fall in the active zone.
    # effort_range_min/max default to 0/0 here; build_model's range_size<=0 fallback
    # then auto-derives a tight per-batch range from just the soldiers/duties it sees,
    # rather than a caller stamping one whole-job range onto every batch (see below).
    #
    # Resolution must be large enough that even the smallest duty's weight rounds to
    # a meaningful integer after (effort_per_milli × block_score × resolution) //
    # range_size.  At 1_000 all 1-day duties collapsed to weight=1 (via max(1,...))
    # regardless of actual score, making the L1 objective blind to score differences.
    # That problem was much worse when range_size was stamped from the WHOLE job
    # (hence 100_000 was needed); now that it's scoped per batch, 20_000 keeps small
    # duties distinguishable in typical batches while giving CP-SAT a much smaller
    # value range to search than 100_000 did.
    effort_resolution: int = 20_000
    effort_range_min: int = 0   # min effort_offset across soldiers (EFFORT_SCALE units)
    effort_range_max: int = 0   # max possible effort_offset including worst-case accumulation
    # Infeasibility relaxation ceilings: R relaxes first up to relax_r_ceiling,
    # then T relaxes up to relax_t_ceiling. Invariant: relax_t_ceiling <= relax_r_ceiling.
    relax_r_ceiling: int = 20
    relax_t_ceiling: int = 10
    # Decomposition + chronological calendar-window batching.
    batching_enabled: bool = True
    batch_window_days: int = 28
    batch_time_limit_seconds: int = 120
    # Decomposition strategy: "interleaved" (default) | "effort_rounds" | "calendar" | "none".
    # "interleaved": sort duties by date/score/type, deal round-robin into N batches so each
    #   batch gets a representative mix; all soldiers compete per batch with effort carry-forward.
    # "effort_rounds": legacy — chunks soldiers into disjoint groups (structurally unfair).
    # "calendar": chunks duties into non-overlapping date windows; all soldiers per batch.
    # "none": single whole-problem solve (correct but slow for large instances).
    decomposition: str = "interleaved"
    # Disjoint Phase-1 group size for effort-round decomposition.
    round_soldier_count: int = 20
    # Target duties per batch for interleaved decomposition. Smaller batches mean
    # smaller CP-SAT models (less branching) AND a tighter per-batch effort_resolution
    # denominator (see effort_resolution above), both of which make individual solves
    # converge faster. 200 let large runs grind through a handful of huge,
    # slow-to-stall batches; 50 trades a few more batches (more progress_cb overhead,
    # negligible) for each one being meaningfully cheaper to solve.
    interleaved_batch_size: int = 50
    # Search workers for CP-SAT. 1 = fully deterministic (fixed seed produces identical
    # results every run). >1 = parallel workers race each other; faster but non-deterministic
    # even with a fixed seed because the winning worker depends on CPU scheduling.
    num_workers: int = 1
    # Lexicographic second-stage tie-break, applied after the main L1 solve
    # reaches OPTIMAL/FEASIBLE: pins L1 dispersion to its proven value, then
    # re-solves with a tie-break objective among solutions L1 can't
    # distinguish (see apply_tiebreak_objective). "off" preserves today's
    # single-stage behaviour exactly.
    tiebreak_mode: Literal["off", "range"] = "range"
    tiebreak_time_limit_seconds: int = 20
    # When True, duties whose node_quotas constraint left them unfilled after
    # the main solve are retried once with each unsatisfied node_id replaced
    # by its hierarchy parent (see solver._relax_unsatisfiable_quotas), widening
    # the eligible pool to the parent's whole subtree (siblings included).
    # Requires the caller to also pass `node_parents` to `solve()`; without it
    # (or with this False) no quota relaxation is attempted. Off by default —
    # auto-relaxing silently changes which sub-unit actually filled a quota'd
    # slot, which callers may want to surface for manual approval instead
    # (see Task B4, not yet built).
    auto_relax_node_quotas: bool = False
    # Hard constraint by default: a soldier whose id appears in a DutyBlock's soldier
    # via SoldierInput.weapon_ineligible_duty_block_ids is never assigned to that block.
    # False relaxes this for the whole run (see algorithm_bridge.resolve_solver_settings
    # for the system-setting default and per-run override).
    enforce_weapon_qualification: bool = True


@dataclass
class BatchShiftFill:
    """Per-shift fill summary within one batch."""
    shift_id: uuid.UUID | None  # None until bridge fills it from block_to_shift
    required_count: int
    assigned_count: int
    eligible_count: int = 0
    available_count: int = 0
    blocker_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class SaturationCluster:
    """Diagnostic: a group of date-overlapping duties left unassigned because
    every eligible soldier is already committed elsewhere on those exact dates.

    Raising R/T density ceilings cannot fix this — it's a proven structural
    shortfall (free_count == 0), reached only after the relaxation search
    (see solver._search_relaxation_ladder) has exhausted the ceiling.
    """
    date_from: date
    date_to: date
    shift_ids: list[uuid.UUID]
    eligible_pool_size: int
    free_count: int
    competing_duty_types: list[tuple[uuid.UUID, int]]


@dataclass
class BatchResult:
    """Diagnostic record for one calendar-window batch."""
    batch_index: int          # global sequential index across all components
    component_index: int      # which connected component
    date_from: date
    date_to: date
    duty_count: int           # total duty slots in batch
    soldier_count: int
    assigned_count: int
    unassigned_count: int
    outcome: str              # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "CANCELLED"
    relaxations: list[str]    # e.g. ["R→17", "R→19"]
    wall_time_seconds: float
    shifts: list[BatchShiftFill] = field(default_factory=list)
    saturation_clusters: list[SaturationCluster] = field(default_factory=list)
    impacted_soldiers: list[dict] = field(default_factory=list)


@dataclass
class Assignment:
    """A single (duty, soldier) assignment from the solver."""
    duty_id: uuid.UUID
    soldier_id: uuid.UUID


@dataclass
class SolverResult:
    """Complete solver output with status, assignments, and metrics."""
    assignments: list[Assignment]
    status: str
    objective_value: float | None = None
    seed: int = 0
    solver_metrics: dict[str, Any] = field(default_factory=dict)
    relaxed: list[str] = field(default_factory=list)
    batch_results: list[BatchResult] = field(default_factory=list)
    # One entry per (duty, node) quota relaxed from a child node to its parent
    # by solver._relax_unsatisfiable_quotas (see SolverSettings.auto_relax_node_quotas).
    # Shape: {"duty_id": UUID, "original_node_id": UUID, "relaxed_node_id": UUID, "count": int}.
    relaxed_node_quotas: list[dict] = field(default_factory=list)


@dataclass
class CandidateInfo:
    """Analysis of a single candidate soldier for explainability."""
    soldier_id: uuid.UUID
    blocked: bool = False
    blocking_constraints: list[str] = field(default_factory=list)
    pre_effort_score: float | None = None   # effort_offset / EFFORT_SCALE (historical effort)
    post_effort_score: float | None = None  # effort after this assignment


@dataclass
class AssignmentExplanation:
    """Per-assignment explanation with candidate analysis."""
    duty_id: uuid.UUID
    assigned_soldier_id: uuid.UUID
    candidates: list[CandidateInfo] = field(default_factory=list)
    tiebreaker_note: str | None = None


@dataclass
class ExplanationData:
    """Full explainability output with global metrics."""
    per_assignment: list[AssignmentExplanation] = field(default_factory=list)
    global_metrics_before: dict[str, Any] = field(default_factory=dict)
    global_metrics_after: dict[str, Any] = field(default_factory=dict)
    algorithm_version: str = "cp-sat-1.0"
    solver_seed: int = 0


@dataclass
class ReserveEntry:
    """A (duty, primary, reserve) tuple from the hierarchy walk."""
    duty_id: uuid.UUID
    primary_soldier_id: uuid.UUID
    reserve_soldier_id: uuid.UUID


@dataclass
class ReserveLink:
    """A (reserve_assignment_id, primary_assignment_id, distance) tuple from post-solve linking."""
    reserve_assignment_id: uuid.UUID
    primary_assignment_id: uuid.UUID
    hierarchy_distance: int
