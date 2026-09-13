from __future__ import annotations

import uuid
from bisect import bisect_left, bisect_right
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
    #
    # Sorted by start_date, and paired with a parallel end_date array, so the
    # overlap check can binary-search both edges of the possible-overlap
    # window instead of scanning. This relies on a soldier's own assignments
    # never overlapping each other within a single solve -- guaranteed by the
    # solver's own "at most one duty per soldier per day" hard constraint
    # (model.py, applied uniformly across primary AND reserve slots, since
    # both draw on the same soldier-day capacity) -- which means start_date
    # order here is also non-decreasing end_date order.
    soldier_duties: dict[uuid.UUID, list[tuple[uuid.UUID, DutyBlock]]] = defaultdict(list)
    for a2 in assignments:
        soldier_duties[a2.soldier_id].append((a2.duty_id, duty_map[a2.duty_id]))
    soldier_duty_starts: dict[uuid.UUID, list] = {}
    soldier_duty_ends: dict[uuid.UUID, list] = {}
    for sid, duty_list in soldier_duties.items():
        duty_list.sort(key=lambda item: item[1].start_date)
        soldier_duty_starts[sid] = [item[1].start_date for item in duty_list]
        soldier_duty_ends[sid] = [item[1].end_date for item in duty_list]

    # Soldier-only, duty-independent — hoisted out of the per-assignment loop
    # below instead of recomputing it up to len(assignments) times per soldier.
    soldier_pre_effort: dict[uuid.UUID, float | None] = {
        s.id: (s.effort_offset / EFFORT_SCALE if EFFORT_SCALE > 0 else None) for s in soldiers
    }

    per_assignment: list[AssignmentExplanation] = []
    for a in assignments:
        duty = duty_map[a.duty_id]
        if duty.is_reserve:
            # Reserve-duty explanations are never persisted or read: persist_results
            # (algorithm_bridge.py) only looks up explanation_map for non-reserve
            # blocks. Building the full per-soldier candidate list for every
            # reserve assignment too — often as numerous as the primary ones —
            # was pure wasted work, and was the dominant cost of the "שומר
            # הצעות" (saving proposals) phase on large/long-range runs.
            continue
        candidates: list[CandidateInfo] = []

        for s in soldiers:
            blocking: list[str] = []
            if duty.duty_type_id in s.exempted_duty_type_ids:
                blocking.append("exemption")
            if duty.id in s.weapon_ineligible_duty_block_ids:
                blocking.append("weapon_ineligible")
            for cs, ce in s.approved_constraint_dates:
                if cs < duty.end_date and ce >= duty.start_date:
                    blocking.append("personal_constraint")
                    break
            s_duty_list = soldier_duties.get(s.id)
            if s_duty_list:
                # [lo, hi) is exactly the window of this soldier's own duties
                # that overlap `duty` -- see the invariant note above.
                lo = bisect_right(soldier_duty_ends[s.id], duty.start_date)
                hi = bisect_left(soldier_duty_starts[s.id], duty.end_date)
                for other_duty_id, _other_duty in s_duty_list[lo:hi]:
                    if other_duty_id != a.duty_id:
                        blocking.append("overlap")
                        break

            pre_effort = soldier_pre_effort[s.id]
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
