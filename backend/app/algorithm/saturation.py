"""Diagnose why duties remain unassigned after the relaxation search is
exhausted (see solver._search_relaxation_ladder). Pure module: no DB imports,
matching the rest of app/algorithm/.
"""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import date

from app.algorithm.availability import is_eligible
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SaturationCluster,
    SoldierInput,
)


def _eligible(soldier: SoldierInput, duty: DutyBlock) -> bool:
    """Mirrors solver._eligible_pairs' filter for a single (soldier, duty) pair."""
    return is_eligible(soldier, duty)


def _date_ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Exclusive-end-date overlap, matching DutyBlock's [start_date, end_date) convention."""
    return a_start < b_end and b_start < a_end


def _cluster_by_date_overlap(duties: Sequence[DutyBlock]) -> list[list[DutyBlock]]:
    """Group duties into transitively date-overlapping clusters (union-find).

    O(n^2) pairwise comparison — fine here since `duties` is only the small
    leftover-unassigned set, never the full duty list.
    """
    n = len(duties)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if _date_ranges_overlap(duties[i].start_date, duties[i].end_date,
                                    duties[j].start_date, duties[j].end_date):
                union(i, j)

    groups: dict[int, list[DutyBlock]] = {}
    for i, d in enumerate(duties):
        groups.setdefault(find(i), []).append(d)
    return list(groups.values())


def _analyze_cluster(
    cluster_duties: Sequence[DutyBlock],
    full_pool: Sequence[SoldierInput],
    commitments_by_soldier: dict[uuid.UUID, list[tuple[date, date, uuid.UUID]]],
) -> SaturationCluster:
    date_from = min(d.start_date for d in cluster_duties)
    date_to = max(d.end_date for d in cluster_duties)

    eligible_total = 0
    free_count = 0
    competing: Counter[uuid.UUID] = Counter()

    for soldier in full_pool:
        if not any(_eligible(soldier, d) for d in cluster_duties):
            continue
        eligible_total += 1
        commitments = commitments_by_soldier.get(soldier.id, [])
        busy_duty_types = [
            duty_type_id for (start, end, duty_type_id) in commitments
            if _date_ranges_overlap(start, end, date_from, date_to)
        ]
        if busy_duty_types:
            competing.update(busy_duty_types)
        else:
            free_count += 1

    return SaturationCluster(
        date_from=date_from,
        date_to=date_to,
        shift_ids=[d.id for d in cluster_duties],
        eligible_pool_size=eligible_total,
        free_count=free_count,
        competing_duty_types=sorted(competing.items(), key=lambda kv: -kv[1]),
    )


def analyze_saturation(
    unassigned: Sequence[DutyBlock],
    full_pool: Sequence[SoldierInput],
    all_assignments: Sequence[Assignment],
    existing: Sequence[ExistingAssignment],
    duty_by_id: dict[uuid.UUID, DutyBlock],
) -> list[SaturationCluster]:
    """Cluster `unassigned` duties by date overlap and explain each cluster:
    how many eligible soldiers exist, how many are free, and what duty types
    the busy ones are already committed to during that window.
    """
    if not unassigned:
        return []

    commitments_by_soldier: dict[uuid.UUID, list[tuple[date, date, uuid.UUID]]] = {}
    for e in existing:
        commitments_by_soldier.setdefault(e.soldier_id, []).append(
            (e.start_date, e.end_date, e.duty_type_id)
        )
    for a in all_assignments:
        d = duty_by_id[a.duty_id]
        commitments_by_soldier.setdefault(a.soldier_id, []).append(
            (d.start_date, d.end_date, d.duty_type_id)
        )

    clusters = _cluster_by_date_overlap(list(unassigned))
    return [_analyze_cluster(c, full_pool, commitments_by_soldier) for c in clusters]
