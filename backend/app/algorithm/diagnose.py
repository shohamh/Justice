from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput


def _duty_days(d: DutyBlock) -> list[date]:
    days: list[date] = []
    dt = d.start_date
    while dt < d.end_date:
        days.append(dt)
        dt += timedelta(days=1)
    return days


def _soldier_blocked_on(s: SoldierInput, day: date) -> bool:
    for cs, ce in s.approved_constraint_dates:
        if cs <= day <= ce:
            return True
    return False


def diagnose_infeasibility(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    duty_type_names: dict[uuid.UUID, str],
) -> list[str]:
    """Return a list of Hebrew human-readable reasons why the assignment is infeasible."""
    reasons: list[str] = []

    # Pre-compute existing-assignment dates per soldier
    existing_dates: dict[uuid.UUID, set[date]] = defaultdict(set)
    for ea in existing:
        d = ea.start_date
        while d < ea.end_date:
            existing_dates[ea.soldier_id].add(d)
            d += timedelta(days=1)

    def _eligible_for_block(s: SoldierInput, d: DutyBlock) -> bool:
        if d.duty_type_id in s.exempted_duty_type_ids:
            return False
        days = _duty_days(d)
        if any(_soldier_blocked_on(s, day) for day in days):
            return False
        if any(day in existing_dates[s.id] for day in days):
            return False
        return True

    # ── Check 1: any duty block with zero eligible soldiers ──────────
    zero_eligible_types: dict[uuid.UUID, list[date]] = defaultdict(list)
    for d in duties:
        eligible_count = sum(1 for s in soldiers if _eligible_for_block(s, d))
        if eligible_count == 0:
            zero_eligible_types[d.duty_type_id].append(d.start_date)

    for dt_id, bad_dates in zero_eligible_types.items():
        dt_name = duty_type_names.get(dt_id, str(dt_id))
        if len(bad_dates) == 1:
            reasons.append(
                f"אין חיילים כשירים לסוג תורנות '{dt_name}' בתאריך {bad_dates[0]}"
            )
        else:
            dates_str = ", ".join(str(d) for d in sorted(bad_dates)[:3])
            suffix = f" ועוד {len(bad_dates) - 3}" if len(bad_dates) > 3 else ""
            reasons.append(
                f"אין חיילים כשירים לסוג תורנות '{dt_name}' ב-{len(bad_dates)} תאריכים ({dates_str}{suffix})"
            )

    # ── Check 2: per duty-type, max concurrent demand > eligible pool ─
    type_duties: dict[uuid.UUID, list[DutyBlock]] = defaultdict(list)
    for d in duties:
        type_duties[d.duty_type_id].append(d)

    for dt_id, dt_blocks in type_duties.items():
        if dt_id in zero_eligible_types:
            continue  # already reported above
        dt_name = duty_type_names.get(dt_id, str(dt_id))

        # Eligible pool for this type (ignoring date-specific constraints for the pool count)
        eligible_pool = [
            s for s in soldiers
            if dt_id not in s.exempted_duty_type_ids
        ]
        pool_size = len(eligible_pool)

        # Find the day with the most concurrent blocks of this type
        all_days: set[date] = set()
        for d in dt_blocks:
            all_days.update(_duty_days(d))

        max_concurrent = max(
            sum(1 for d in dt_blocks if d.start_date <= day <= d.end_date)
            for day in all_days
        ) if all_days else 0

        if pool_size < max_concurrent:
            reasons.append(
                f"סוג תורנות '{dt_name}': נדרשים {max_concurrent} חיילים בו-זמנית "
                f"אך רק {pool_size} כשירים לסוג זה"
            )

    # ── Check 3: global daily overload ───────────────────────────────
    # On any single day, if total required concurrent slots > total active soldiers
    all_days_global: set[date] = set()
    for d in duties:
        all_days_global.update(_duty_days(d))

    total_soldiers = len(soldiers)
    for day in sorted(all_days_global):
        concurrent_slots = sum(
            1 for d in duties if d.start_date <= day <= d.end_date
        )
        # Count soldiers free on this day (not in existing assignments)
        available = sum(
            1 for s in soldiers if day not in existing_dates[s.id]
        )
        if concurrent_slots > available:
            reasons.append(
                f"ב-{day}: נדרשים {concurrent_slots} חיילים אך רק {available} פנויים "
                f"(מתוך {total_soldiers})"
            )
            break  # report only the first such day to avoid flooding

    return reasons
