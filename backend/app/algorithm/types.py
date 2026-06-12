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
    # Count-space prior load: recent effective duty score × 5 (reserve=1, primary=5).
    # Used by the L1 fairness objective (small eligibility groups only) to balance
    # total load (recent + new). Set by the algorithm_bridge.
    recent_load: int = 0


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


@dataclass
class SolverSettings:
    """CP-SAT solver configuration.

    T: density hard cap (duty-days per rolling window)
    W: rolling window length in days
    alpha: score-preference weight (higher = stronger preference for low-score soldiers)
    """
    T: int = 7
    W: int = 14
    alpha: Decimal = Decimal("1.0")
    time_limit_seconds: int = 30
    seed: int | None = None
    reserve_hierarchy_weight: Decimal = Decimal("0.5")
    # Fairness L1 in count-space: effort × effort_resolution, rounded to integers.
    effort_resolution: int = 10_000
    # Decomposition + chronological batching (keeps each L1 solve small/tractable).
    batching_enabled: bool = True
    batch_size: int = 50
    batch_time_limit_seconds: int = 10


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
