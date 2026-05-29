from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from app.algorithm.types import (
    Assignment,
    AssignmentExplanation,
    CandidateInfo,
    DutyBlock,
    ExplanationData,
    SoldierInput,
)


def build_explanations(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    assignments: Sequence[Assignment],
    global_before: dict,
    global_after: dict,
    solver_seed: int,
) -> ExplanationData:
    duty_map = {d.id: d for d in duties}

    per_assignment: list[AssignmentExplanation] = []
    for a in assignments:
        duty = duty_map[a.duty_id]
        candidates: list[CandidateInfo] = []

        for s in soldiers:
            blocking: list[str] = []
            if duty.duty_type_id in s.exempted_duty_type_ids:
                blocking.append("exemption")
            for cs, ce in s.approved_constraint_dates:
                if cs <= duty.end_date and ce >= duty.start_date:
                    blocking.append("personal_constraint")
                    break
            for other_a in assignments:
                if other_a.soldier_id == s.id and other_a.duty_id != a.duty_id:
                    other_duty = duty_map[other_a.duty_id]
                    if other_duty.start_date <= duty.end_date and other_duty.end_date >= duty.start_date:
                        blocking.append("overlap")
                        break

            pre = s.cumulative_score
            block_score = duty.score_per_day * Decimal((duty.end_date - duty.start_date).days + 1)
            post = pre + block_score if s.id == a.soldier_id else pre

            candidates.append(CandidateInfo(
                soldier_id=s.id,
                blocked=len(blocking) > 0,
                blocking_constraints=blocking,
                pre_norm_score=pre / Decimal(s.active_days) if s.active_days > 0 else None,
                post_norm_score=post / Decimal(s.active_days) if s.active_days > 0 else None,
            ))

        per_assignment.append(AssignmentExplanation(
            duty_id=a.duty_id,
            assigned_soldier_id=a.soldier_id,
            candidates=candidates,
            tiebreaker_note="Selected by solver objective optimisation",
        ))

    return ExplanationData(
        per_assignment=per_assignment,
        global_metrics_before=dict(global_before),
        global_metrics_after=dict(global_after),
        algorithm_version="cp-sat-1.0",
        solver_seed=solver_seed,
    )
