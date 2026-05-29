from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


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


@dataclass
class DutyBlock:
    """A duty block (shift) to be assigned to a soldier."""
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    score_per_day: Decimal


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

    K: max normalised-score variance between soldiers
    T: density soft cap (duty-days per rolling window)
    W: rolling window length in days
    alpha: min_gap spacing reward weight
    beta: density penalty weight
    """
    K: Decimal = Decimal("8")
    T: int = 7
    W: int = 14
    alpha: Decimal = Decimal("1.0")
    beta: Decimal = Decimal("2.0")
    time_limit_seconds: int = 30
    seed: int | None = None


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
    pre_norm_score: Decimal | None = None
    post_norm_score: Decimal | None = None


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
