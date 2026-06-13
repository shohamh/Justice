from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

# Scale factor for converting Decimal effort scores to CP-SAT integers.
# Lives here (the pure, dependency-free types module) so both the solver
# (app.algorithm.model) and the effort service (app.services.effort_score)
# can share it without the solver importing any DB code.
EFFORT_SCALE = 1_000_000_000  # 10^9

@dataclass
class SoldierInput:
    """A soldier eligible for duty assignment."""
    id: uuid.UUID
    enrolled_at: date
    cumulative_score: Decimal
    active_days: int
    hierarchy_node_id: uuid.UUID | None = None
    approved_constraint_dates: list[tuple[date, date]] = field(default_factory=list)
    exempted_duty_type_ids: set[uuid.UUID] = field(default_factory=set)
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


@dataclass
class ExistingAssignment:
    """An already-published assignment for min_gap continuity."""
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date
    is_reserve: bool = False


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
    time_limit_seconds: int = 30
    seed: int | None = None
    reserve_hierarchy_weight: Decimal = Decimal("0.5")
    # Fairness L1 in count-space: effort × effort_resolution, rounded to integers.
    effort_resolution: int = 10_000
    # Infeasibility relaxation ceilings: R relaxes first up to relax_r_ceiling,
    # then T relaxes up to relax_t_ceiling. Invariant: relax_t_ceiling <= relax_r_ceiling.
    relax_r_ceiling: int = 20
    relax_t_ceiling: int = 10
    # Decomposition + chronological calendar-window batching.
    batching_enabled: bool = True
    batch_window_days: int = 28
    batch_time_limit_seconds: int = 10
    # Decomposition strategy: "effort_rounds" (default) | "calendar" | "none".
    decomposition: str = "effort_rounds"
    # Disjoint Phase-1 group size for effort-round decomposition.
    round_soldier_count: int = 50


@dataclass
class BatchShiftFill:
    """Per-shift fill summary within one batch."""
    shift_id: uuid.UUID | None  # None until bridge fills it from block_to_shift
    required_count: int
    assigned_count: int


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
