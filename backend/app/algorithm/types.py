from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class SoldierInput:
    id: uuid.UUID
    enrolled_at: date
    cumulative_score: Decimal
    active_days: int
    hierarchy_node_id: uuid.UUID | None = None
    approved_constraint_dates: list[tuple[date, date]] = field(default_factory=list)
    exempted_duty_type_ids: set[uuid.UUID] = field(default_factory=set)


@dataclass
class DutyBlock:
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    score_per_day: Decimal


@dataclass
class ExistingAssignment:
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date


@dataclass
class SolverSettings:
    K: Decimal = Decimal("8")
    T: int = 7
    W: int = 14
    alpha: Decimal = Decimal("1.0")
    beta: Decimal = Decimal("2.0")
    time_limit_seconds: int = 30
    seed: int | None = None


@dataclass
class Assignment:
    duty_id: uuid.UUID
    soldier_id: uuid.UUID


@dataclass
class SolverResult:
    assignments: list[Assignment]
    status: str
    objective_value: float | None = None
    seed: int = 0
    solver_metrics: dict = field(default_factory=dict)
    relaxed: list[str] = field(default_factory=list)


@dataclass
class CandidateInfo:
    soldier_id: uuid.UUID
    blocked: bool = False
    blocking_constraints: list[str] = field(default_factory=list)
    pre_norm_score: Decimal | None = None
    post_norm_score: Decimal | None = None


@dataclass
class AssignmentExplanation:
    duty_id: uuid.UUID
    assigned_soldier_id: uuid.UUID
    candidates: list[CandidateInfo] = field(default_factory=list)
    tiebreaker_note: str | None = None


@dataclass
class ExplanationData:
    per_assignment: list[AssignmentExplanation] = field(default_factory=list)
    global_metrics_before: dict = field(default_factory=dict)
    global_metrics_after: dict = field(default_factory=dict)
    algorithm_version: str = "cp-sat-1.0"
    solver_seed: int = 0


@dataclass
class ReserveEntry:
    duty_id: uuid.UUID
    primary_soldier_id: uuid.UUID
    reserve_soldier_id: uuid.UUID
