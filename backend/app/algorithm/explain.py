from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from app.algorithm.types import (
    Assignment,
    AssignmentExplanation,
    CandidateInfo,
    DutyBlock,
    ExplanationData,
    SoldierInput,
)
from app.services.effort_score import EFFORT_SCALE


def build_explanations(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    assignments: Sequence[Assignment],
    global_before: dict[str, Any],
    global_after: dict[str, Any],
    solver_seed: int,
) -> ExplanationData:
    duty_map = {d.id: d for d in duties}

    # Pre-build soldier → assigned duties lookup so the overlap check below is
    # O(avg_assignments_per_soldier) rather than O(len(assignments)), avoiding
    # an O(A² × S) triple-nested loop that hangs for large runs.
    soldier_duties: dict[uuid.UUID, list[tuple[uuid.UUID, DutyBlock]]] = defaultdict(list)
    for a2 in assignments:
        soldier_duties[a2.soldier_id].append((a2.duty_id, duty_map[a2.duty_id]))

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
            for other_duty_id, other_duty in soldier_duties.get(s.id, []):
                if other_duty_id != a.duty_id:
                    if other_duty.start_date <= duty.end_date and other_duty.end_date >= duty.start_date:
                        blocking.append("overlap")
                        break

            pre_effort = s.effort_offset / EFFORT_SCALE if EFFORT_SCALE > 0 else None
            blocked = len(blocking) > 0
            post_effort = None
            if not blocked:
                block_milli = int(
                    float(duty.score_per_day) * ((duty.end_date - duty.start_date).days) * 1000
                )
                post_milli = s.effort_offset + s.effort_per_milli * block_milli
                post_effort = post_milli / EFFORT_SCALE

            candidates.append(CandidateInfo(
                soldier_id=s.id,
                blocked=blocked,
                blocking_constraints=blocking,
                pre_effort_score=float(pre_effort) if pre_effort is not None else None,
                post_effort_score=float(post_effort) if post_effort is not None else None,
            ))

        unblocked_count = sum(1 for c in candidates if not c.blocked)
        tiebreaker_note = None if unblocked_count <= 1 else "lowest_post_effort_score"

        per_assignment.append(AssignmentExplanation(
            duty_id=a.duty_id,
            assigned_soldier_id=a.soldier_id,
            candidates=candidates,
            tiebreaker_note=tiebreaker_note,
        ))

    return ExplanationData(
        per_assignment=per_assignment,
        global_metrics_before=dict(global_before),
        global_metrics_after=dict(global_after),
        algorithm_version="cp-sat-1.0",
        solver_seed=solver_seed,
    )
