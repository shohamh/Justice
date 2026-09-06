from __future__ import annotations

import uuid
import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session
from app.services.sql_arrays import uuid_any

from app.algorithm.duration import combine_date_time
from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyDismissal,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    ScoreAdjustment,
    ScoreProjectionDirtyBucket,
    ScoreProjectionQuarterTotal,
    ScoreProjectionState,
    Soldier,
    SoldierExemption,
    SoldierQuarterScoreProjection,
    SoldierScoreProjection,
)
from app.algorithm.duration import calendar_days_touched, score_days
from app.services.eligibility import inferred_service_type
from app.auth.authz import scope_root_ids
from app.services.authority import can_view_soldier_scope

_UNSET: object = object()
_SCORE_QUANT = Decimal("0.000001")
logger = logging.getLogger(__name__)


def _duty_type_scores(session: Session) -> dict[uuid.UUID, Decimal]:
    return {dt.id: dt.score_per_day for dt in session.execute(select(DutyType)).scalars().all()}


def _get_multiplier_setting(session: Session, key: str, default: str) -> Decimal:
    from app.services.settings_loader import SettingNotFound, get_setting
    try:
        return Decimal(str(get_setting(session, key)))
    except SettingNotFound:
        return Decimal(default)


def effective_duty_days(
    session: Session, *, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[date, uuid.UUID, uuid.UUID, Decimal]]:
    """Expand every published assignment to (date, effective_soldier_id, duty_type_id, multiplier).

    Multiplier depends on:
    - Primary assignment: 1.0, or dismissed_multiplier if a DutyDismissal covers that day
    - Reserve assignment: called_up_multiplier if in called-up range, else standby_multiplier
    Overrides (replacements) still reassign effective_soldier_id.
    """
    return [
        (
            row["day"],
            row["effective_soldier_id"],
            row["duty_type_id"],
            row["weighted_multiplier"],
        )
        for row in _effective_duty_day_rows(
            session,
            statuses=["published"],
            date_from=date_from,
            date_to=date_to,
        )
    ]


def _effective_duty_spans_impl(
    session: Session,
    *,
    statuses: list[str],
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Shared implementation behind `effective_duty_spans` (statuses=["published"],
    the scoring/effort/fairness source of truth — never widen its caller-visible
    contract to include drafts) and `effective_duty_spans_with_drafts`
    (statuses=["published", "algorithm_draft"], display surfaces only).
    Assignments matching `statuses` are expanded per day with overrides applied,
    then re-merged into contiguous runs where the effective soldier is
    unchanged. Degrades to the original block when there are no overrides;
    cancelled days (NULL effective) break runs and are dropped. Optionally
    filtered to soldier_ids and to spans overlapping [date_from, date_to]."""
    assignments = (
        session.execute(select(DutyAssignment).where(DutyAssignment.status.in_(statuses)))
        .scalars()
        .all()
    )
    overrides = {
        (o.duty_assignment_id, o.date): o
        for o in session.execute(select(DutyDayOverride)).scalars().all()
    }
    dismissal_ranges: dict[uuid.UUID, list[tuple[date, date]]] = {}
    for d in session.execute(select(DutyDismissal)).scalars().all():
        dismissal_ranges.setdefault(d.duty_assignment_id, []).append((d.dismissed_from, d.dismissed_to))

    def _is_dismissed(assignment_id: uuid.UUID, day: date) -> bool:
        return any(df <= day <= dt for df, dt in dismissal_ranges.get(assignment_id, []))

    spans: list[dict[str, Any]] = []
    for a in assignments:
        last_assignment_day = a.end_date - timedelta(days=1)

        def _make_span(cur: Any, run_start: date, run_end: date, *, _a: DutyAssignment = a) -> dict[str, Any]:
            # A run only carries the assignment's real clock time on the edge
            # day(s) that match the assignment's own boundaries; a run that
            # was split off mid-assignment by an override has no wall-clock
            # time of its own, so it degrades to a full calendar day there.
            start_time = _a.start_time if run_start == _a.start_date else "00:00"
            end_time = _a.end_time if run_end == last_assignment_day else "23:59"
            original_owner = cur == _a.soldier_id
            return {
                "assignment_id": _a.id,
                "soldier_id": cur,
                "duty_type_id": _a.duty_type_id,
                "duty_location_id": _a.duty_location_id,
                "start_date": run_start,
                # Exclusive, matching DutyAssignment/DutyShift's own convention
                # (run_end above is the run's last INCLUSIVE day).
                "end_date": run_end + timedelta(days=1),
                "start_time": start_time,
                "end_time": end_time,
                "start_at": combine_date_time(run_start, start_time),
                "end_at": combine_date_time(run_end, end_time),
                "shift_id": _a.duty_shift_id,
                "is_reserve": _a.is_reserve,
                "called_up_from": _a.called_up_from,
                "called_up_to": _a.called_up_to,
                "weapon_ineligible": _a.weapon_ineligible if original_owner else False,
                "weapon_ineligible_reason": _a.weapon_ineligible_reason if original_owner else None,
                "status": _a.status,
            }

        cur: object = _UNSET
        run_start: date | None = None
        run_end: date | None = None
        day = a.start_date
        while day < a.end_date:
            ov = overrides.get((a.id, day))
            if ov is not None:
                eff = ov.effective_soldier_id
            elif _is_dismissed(a.id, day):
                eff = None
            else:
                eff = a.soldier_id
            if eff == cur:
                run_end = day
            else:
                if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
                    spans.append(_make_span(cur, run_start, run_end))
                cur = eff
                run_start = day if eff is not None else None
                run_end = day if eff is not None else None
            day += timedelta(days=1)
        if cur not in (None, _UNSET) and run_start is not None and run_end is not None:
            spans.append(_make_span(cur, run_start, run_end))
    result: list[dict[str, Any]] = []
    for sp in spans:
        if soldier_ids is not None and sp["soldier_id"] not in soldier_ids:
            continue
        if date_from is not None and sp["end_date"] <= date_from:
            continue
        if date_to is not None and sp["start_date"] > date_to:
            continue
        result.append(sp)
    result.sort(key=lambda s: s["start_date"])
    return result


def effective_duty_spans(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Published assignments only — the scoring/effort/fairness source of
    truth. Do not widen this function's status filter; add a new function
    (see `effective_duty_spans_with_drafts`) for any display surface that
    needs drafts."""
    return _effective_duty_spans_impl(
        session, statuses=["published"], soldier_ids=soldier_ids, date_from=date_from, date_to=date_to,
    )


def effective_duty_spans_with_drafts(
    session: Session,
    *,
    soldier_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Published + algorithm_draft assignments, for display surfaces only
    (e.g. a soldier's own upcoming-duties widget). Never call this from
    scoring, effort, or fairness code — use `effective_duty_spans` there."""
    return _effective_duty_spans_impl(
        session, statuses=["published", "algorithm_draft"], soldier_ids=soldier_ids, date_from=date_from, date_to=date_to,
    )


def shift_count_by_soldier(session: Session) -> dict[uuid.UUID, int]:
    """Count distinct published assignments per effective soldier (ignoring duration)."""
    counts: dict[uuid.UUID, set] = defaultdict(set)
    for sp in effective_duty_spans(session):
        counts[sp["soldier_id"]].add(sp["assignment_id"])
    return {s_id: len(asgns) for s_id, asgns in counts.items()}


def duty_score_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    """Duty score per effective soldier.

    Served from the projection tables when the writer invariant holds (backfill
    complete, no dirty markers); falls back to canonical day-expansion
    otherwise. Values may differ from legacy by <1e-6 per bucket due to
    6-decimal quantization at write time.
    """
    if _projection_state_is_complete(session) and not _any_dirty_markers(session):
        from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION

        rows = session.execute(
            select(
                SoldierScoreProjection.soldier_id,
                SoldierScoreProjection.duty_score,
                SoldierScoreProjection.projection_version,
            )
        ).all()
        return {
            soldier_id: Decimal(duty_score)
            for soldier_id, duty_score, version in rows
            if version == SCORE_PROJECTION_CANONICAL_VERSION
        }

    scores = _duty_type_scores(session)
    out: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for _day, eff, dtid, mult in effective_duty_days(session):
        out[eff] += scores.get(dtid, Decimal("0")) * mult
    return dict(out)


def _any_dirty_markers(session: Session) -> bool:
    from app.db.models import ScoreProjectionDirtyBucket

    row = session.execute(
        select(ScoreProjectionDirtyBucket.id).where(
            or_(
                ScoreProjectionDirtyBucket.status == "dirty",
                and_(
                    ScoreProjectionDirtyBucket.divergence.is_not(None),
                    ScoreProjectionDirtyBucket.divergence != text("'null'::jsonb"),
                    ScoreProjectionDirtyBucket.reconciled_at.is_(None),
                ),
            )
        ).limit(1)
    ).first()
    return row is not None


def adjustments_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    rows = session.execute(
        select(ScoreAdjustment.soldier_id, func.sum(ScoreAdjustment.delta)).group_by(
            ScoreAdjustment.soldier_id
        )
    ).all()
    return {sid: Decimal(total) for sid, total in rows}


def cumulative_score(session: Session, *, soldier_id: uuid.UUID) -> Decimal:
    duty = duty_score_by_soldier(session).get(soldier_id, Decimal("0"))
    adj = adjustments_by_soldier(session).get(soldier_id, Decimal("0"))
    return duty + adj


def _active_duty_type_ids(session: Session) -> set[uuid.UUID]:
    return set(
        session.execute(select(DutyType.id).where(DutyType.active.is_(True))).scalars().all()
    )


def _full_coverage_exempt_dates(
    session: Session, *, soldier_id: uuid.UUID, start: date, end: date
) -> set[date]:
    active_dts = _active_duty_type_ids(session)
    if not active_dts:
        return set()  # no active duty types => "full coverage" undefined; subtract nothing
    covered: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        covered[etid].add(dtid)
    full_types = {etid for etid, dts in covered.items() if active_dts <= dts}
    if not full_types:
        return set()
    result: set[date] = set()
    exemptions = (
        session.execute(
            select(SoldierExemption).where(
                SoldierExemption.soldier_id == soldier_id,
                SoldierExemption.exemption_type_id.in_(full_types),
            )
        )
        .scalars()
        .all()
    )
    for ex in exemptions:
        lo = max(ex.start_date, start)
        hi = min(ex.end_date, end) if ex.end_date is not None else end
        day = lo
        while day <= hi:
            result.add(day)
            day += timedelta(days=1)
    return result


def active_days(session: Session, *, soldier: Soldier) -> int:
    today = date.today()
    reference_date = _active_days_reference_date(session) or soldier.enrolled_at
    effective_start, calculation_end = _active_day_interval(soldier, reference_date, today)
    raw = max(1, (calculation_end - effective_start).days)
    exempt = _full_coverage_exempt_dates(
        session, soldier_id=soldier.id, start=effective_start, end=today
    )
    return max(1, raw - len(exempt))


def effective_active_start(reference_date: date, unit_join_date: date | None) -> date:
    """Return the later of the shared rollout date and the soldier's unit entry."""
    return max(reference_date, unit_join_date) if unit_join_date is not None else reference_date


def _active_days_reference_date(session: Session) -> date | None:
    from app.services.settings_loader import (
        ACTIVE_DAYS_REFERENCE_DATE_KEY,
        SettingNotFound,
        get_setting,
    )

    try:
        return date.fromisoformat(str(get_setting(session, ACTIVE_DAYS_REFERENCE_DATE_KEY)))
    except SettingNotFound:
        # Databases created before the setting was introduced retain the former
        # enrolled-at behavior until their first registration initializes it.
        return None


def _active_day_interval(soldier: Soldier, reference_date: date, today: date) -> tuple[date, date]:
    effective_start = effective_active_start(reference_date, soldier.unit_join_date)
    calculation_end = min(
        end_date
        for end_date in (today, soldier.discharge_date, soldier.left_at)
        if end_date is not None
    )
    return effective_start, calculation_end


def _count_exempt_days(exemptions: list, start: date, end: date) -> int:
    """Count unique exempt days in [start, end], merging overlapping ranges."""
    ranges = []
    for ex in exemptions:
        lo = max(ex.start_date, start)
        hi = min(ex.end_date, end) if ex.end_date is not None else end
        if lo <= hi:
            ranges.append((lo, hi))
    if not ranges:
        return 0
    ranges.sort()
    total = 0
    cur_lo, cur_hi = ranges[0]
    for lo, hi in ranges[1:]:
        if lo <= cur_hi + timedelta(days=1):
            cur_hi = max(cur_hi, hi)
        else:
            total += (cur_hi - cur_lo).days + 1
            cur_lo, cur_hi = lo, hi
    total += (cur_hi - cur_lo).days + 1
    return total


def _bulk_active_days(session: Session, soldiers: list[Soldier]) -> dict[uuid.UUID, int]:
    """Compute active_days for many soldiers using 3 DB queries total instead of 3-per-soldier."""
    today = date.today()
    if not soldiers:
        return {}
    reference_date = _active_days_reference_date(session)

    def raw_days(soldier: Soldier) -> tuple[date, int]:
        effective_start, calculation_end = _active_day_interval(
            soldier, reference_date or soldier.enrolled_at, today
        )
        return effective_start, max(1, (calculation_end - effective_start).days)

    active_dts = _active_duty_type_ids(session)
    if not active_dts:
        return {s.id: raw_days(s)[1] for s in soldiers}

    covered: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        covered[etid].add(dtid)
    full_types = {etid for etid, dts in covered.items() if active_dts <= dts}

    if not full_types:
        return {s.id: raw_days(s)[1] for s in soldiers}

    soldier_ids = [s.id for s in soldiers]
    all_exemptions = (
        session.execute(
            select(SoldierExemption).where(
                SoldierExemption.soldier_id.in_(soldier_ids),
                SoldierExemption.exemption_type_id.in_(full_types),
            )
        )
        .scalars()
        .all()
    )
    exemptions_by_soldier: dict[uuid.UUID, list] = defaultdict(list)
    for ex in all_exemptions:
        exemptions_by_soldier[ex.soldier_id].append(ex)

    result: dict[uuid.UUID, int] = {}
    for s in soldiers:
        effective_start, raw = raw_days(s)
        exempt_count = _count_exempt_days(exemptions_by_soldier.get(s.id, []), effective_start, today)
        result[s.id] = max(1, raw - exempt_count)
    return result


def _effective_duty_day_rows(
    session: Session,
    *,
    statuses: list[str],
    assignment_ids: set[uuid.UUID] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    standby_mult = _get_multiplier_setting(session, "scoring.reserve_standby_multiplier", "0.2")
    called_up_mult = _get_multiplier_setting(session, "scoring.reserve_called_up_multiplier", "1.3")
    dismissed_mult = _get_multiplier_setting(session, "scoring.dismissed_multiplier", "0.0")

    assignments_query = select(DutyAssignment).where(DutyAssignment.status.in_(statuses))
    if assignment_ids is not None:
        if not assignment_ids:
            return []
        assignments_query = assignments_query.where(DutyAssignment.id.in_(assignment_ids))
    if date_from is not None:
        assignments_query = assignments_query.where(DutyAssignment.end_date > date_from)
    if date_to is not None:
        assignments_query = assignments_query.where(DutyAssignment.start_date <= date_to)
    assignments = session.execute(assignments_query).scalars().all()
    if not assignments:
        return []

    scoped_assignment_ids = {assignment.id for assignment in assignments}
    # psycopg rejects statements with more than 65535 bind parameters; large
    # deployments exceed that with a single IN (...) over every assignment.
    override_chunks: list[DutyDayOverride] = []
    dismissal_chunks: list[DutyDismissal] = []
    scoped_ids = sorted(scoped_assignment_ids)
    chunk_size = 30_000
    for offset in range(0, len(scoped_ids), chunk_size):
        id_chunk = scoped_ids[offset : offset + chunk_size]
        overrides_query = select(DutyDayOverride).where(
            DutyDayOverride.duty_assignment_id.in_(id_chunk)
        )
        if date_from is not None:
            overrides_query = overrides_query.where(DutyDayOverride.date >= date_from)
        if date_to is not None:
            overrides_query = overrides_query.where(DutyDayOverride.date <= date_to)
        override_chunks.extend(session.execute(overrides_query).scalars().all())

        dismissals_query = select(DutyDismissal).where(
            DutyDismissal.duty_assignment_id.in_(id_chunk)
        )
        if date_from is not None:
            dismissals_query = dismissals_query.where(DutyDismissal.dismissed_to >= date_from)
        if date_to is not None:
            dismissals_query = dismissals_query.where(DutyDismissal.dismissed_from <= date_to)
        dismissal_chunks.extend(session.execute(dismissals_query).scalars().all())

    overrides = {
        (override.duty_assignment_id, override.date): override
        for override in override_chunks
    }

    dismissals_by_assignment: dict[uuid.UUID, list[DutyDismissal]] = {}
    for dismissal in dismissal_chunks:
        dismissals_by_assignment.setdefault(dismissal.duty_assignment_id, []).append(dismissal)

    rows: list[dict[str, Any]] = []
    for assignment in assignments:
        touched = calendar_days_touched(assignment.start_date, assignment.end_date)
        day_weight = (
            Decimal(
                score_days(
                    assignment.start_date,
                    assignment.end_date,
                    assignment.start_time,
                    assignment.end_time,
                )
            )
            / Decimal(touched)
            if touched > 0
            else Decimal("1")
        )
        day = assignment.start_date
        while day < assignment.end_date:
            if date_to is not None and day > date_to:
                break
            if date_from is not None and day < date_from:
                day += timedelta(days=1)
                continue
            override = overrides.get((assignment.id, day))
            effective_soldier_id = (
                override.effective_soldier_id if override is not None else assignment.soldier_id
            )
            if effective_soldier_id is not None:
                dismissal = next(
                    (
                        dismissal_row
                        for dismissal_row in dismissals_by_assignment.get(assignment.id, [])
                        if dismissal_row.dismissed_from <= day <= dismissal_row.dismissed_to
                    ),
                    None,
                )
                if assignment.forced_call_up_multiplier is not None:
                    multiplier = assignment.forced_call_up_multiplier
                    multiplier_source = "forced_call_up"
                elif assignment.is_reserve:
                    if (
                        assignment.called_up_from is not None
                        and assignment.called_up_to is not None
                        and assignment.called_up_from <= day <= assignment.called_up_to
                    ):
                        multiplier = called_up_mult
                        multiplier_source = "reserve_called_up"
                    else:
                        multiplier = standby_mult
                        multiplier_source = "reserve_standby"
                else:
                    if dismissal is not None:
                        multiplier = dismissed_mult
                        multiplier_source = "dismissal"
                    else:
                        multiplier = Decimal("1.0")
                        multiplier_source = "default"
                rows.append(
                    {
                        "assignment_id": assignment.id,
                        "day": day,
                        "effective_soldier_id": effective_soldier_id,
                        "assignment_soldier_id": assignment.soldier_id,
                        "duty_type_id": assignment.duty_type_id,
                        "day_weight": day_weight,
                        "multiplier": multiplier,
                        "multiplier_source": multiplier_source,
                        "weighted_multiplier": multiplier * day_weight,
                        "override_id": override.id if override is not None else None,
                        "override_date": override.date if override is not None else None,
                        "override_effective_soldier_id": (
                            override.effective_soldier_id if override is not None else None
                        ),
                        "override_reason": override.reason if override is not None else None,
                        "dismissal_id": dismissal.id if dismissal is not None else None,
                        "dismissed_from": dismissal.dismissed_from if dismissal is not None else None,
                        "dismissed_to": dismissal.dismissed_to if dismissal is not None else None,
                        "dismissal_reason": dismissal.reason if dismissal is not None else None,
                    }
                )
            day += timedelta(days=1)
    return rows


def _duty_stats_by_soldier(
    session: Session,
) -> tuple[dict[uuid.UUID, Decimal], dict[uuid.UUID, int]]:
    """Return (score_by_soldier, shift_count_by_soldier) in a single pass — half the queries of
    calling duty_score_by_soldier + shift_count_by_soldier separately."""
    type_scores = _duty_type_scores(session)
    duty_scores: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    assignment_sets: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)

    for row in _effective_duty_day_rows(session, statuses=["published"]):
        effective_soldier_id = row["effective_soldier_id"]
        duty_scores[effective_soldier_id] += (
            type_scores.get(row["duty_type_id"], Decimal("0")) * row["weighted_multiplier"]
        )
        assignment_sets[effective_soldier_id].add(row["assignment_id"])

    return dict(duty_scores), {sid: len(asgns) for sid, asgns in assignment_sets.items()}


def normalised_score(session: Session, *, soldier: Soldier) -> Decimal:
    return cumulative_score(session, soldier_id=soldier.id) / Decimal(
        active_days(session, soldier=soldier)
    )


def globally_exempted_soldier_ids(session: Session) -> set[uuid.UUID]:
    """Return the set of soldier IDs who have an active global exemption today."""
    today = date.today()
    exemptions = (
        session.execute(
            select(SoldierExemption)
            .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
            .where(
                ExemptionType.is_global.is_(True),
                SoldierExemption.revoked_at.is_(None),
                SoldierExemption.start_date <= today,
                or_(
                    SoldierExemption.end_date.is_(None),
                    SoldierExemption.end_date >= today,
                ),
            )
        )
        .scalars()
        .all()
    )
    return {ex.soldier_id for ex in exemptions}


def _active_exemptions_by_soldier(
    session: Session,
) -> dict[uuid.UUID, list[tuple[SoldierExemption, ExemptionType]]]:
    today = date.today()
    rows = session.execute(
        select(SoldierExemption, ExemptionType)
        .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
        .where(
            SoldierExemption.revoked_at.is_(None),
            SoldierExemption.start_date <= today,
            or_(
                SoldierExemption.end_date.is_(None),
                SoldierExemption.end_date >= today,
            ),
        )
    ).all()
    by_soldier: dict[uuid.UUID, list[tuple[SoldierExemption, ExemptionType]]] = defaultdict(list)
    for exemption, ex_type in rows:
        by_soldier[exemption.soldier_id].append((exemption, ex_type))
    return by_soldier


def _exemption_label(exemption: SoldierExemption, ex_type: ExemptionType) -> str:
    category = "גלובלי" if ex_type.is_global else "חלקי"
    if exemption.end_date is not None:
        return f"{ex_type.name} ({category}, עד {exemption.end_date.strftime('%d.%m.%Y')})"
    return f"{ex_type.name} ({category})"


def _q6(value: Decimal | int | str | None) -> Decimal:
    return Decimal(value or "0").quantize(_SCORE_QUANT)


def _score_projection_now() -> datetime:
    return datetime.now(timezone.utc)


def _iter_calendar_quarters(start: date, end: date) -> list[date]:
    """Calendar quarter starts touched by inclusive [start, end]."""
    from app.services.effort_score import quarter_end, quarter_start

    if end < start:
        return []
    current = quarter_start(start)
    last = quarter_start(end)
    quarters: list[date] = []
    while current <= last:
        quarters.append(current)
        current = quarter_end(current) + timedelta(days=1)
    return quarters


def _burden_share_reset_date(session: Session) -> date:
    """Frame of reference for the quarterly-load history window.

    The `fairness.reset_date` setting overrides everything. Without it, ALL
    relevant quarters count: history starts at the calendar quarter containing
    the earliest duty assigned to any soldier (not a fixed look-back window and
    not per-soldier enrollment). With no published duties at all, falls back to
    a two-years-back quarter so callers get a sane empty-ish window.
    """
    from app.services.effort_score import quarter_start
    from app.services.settings_loader import SettingNotFound, get_setting

    try:
        reset_raw = get_setting(session, "fairness.reset_date")
        return date.fromisoformat(str(reset_raw))
    except (SettingNotFound, ValueError, TypeError):
        pass

    first_start = session.execute(
        select(func.min(DutyAssignment.start_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if first_start is not None:
        return quarter_start(first_start)
    return quarter_start(date(date.today().year - 2, date.today().month, 1))


def _reset_date_overrides(session: Session) -> dict[str, str]:
    """Raw {node_id_str: iso_date} from fairness.reset_date_overrides, or {}
    if unset/malformed. Validation of well-formedness happens at write time
    (settings_loader.validate_settings_update) — this is a defensive read."""
    from app.services.settings_loader import RESET_DATE_OVERRIDES_KEY, SettingNotFound, get_setting

    try:
        raw = get_setting(session, RESET_DATE_OVERRIDES_KEY)
    except SettingNotFound:
        return {}
    return raw if isinstance(raw, dict) else {}


def _resolve_reset_date_from_path(
    path_ids: list[uuid.UUID], overrides: dict[str, str], default: date
) -> date:
    """Nearest-ancestor override, else default. path_ids is root-to-self
    (HierarchyNode.path_ids convention — see hierarchy.py's
    `path_ids = [*parent.path_ids, node.id]`), so walking it in reverse
    checks the soldier's own node first, then each ancestor toward the root."""
    for node_id in reversed(path_ids):
        raw = overrides.get(str(node_id))
        if raw is not None:
            return date.fromisoformat(raw)
    return default


def _earliest_configured_reset_date(session: Session) -> date:
    """The earliest reset date reachable by ANY soldier under the current
    configuration: the global default, or any hierarchy override, whichever
    is earliest. Used as the duty-day query/quarter-list floor by both
    compute_effort_data and compute_burden_share_breakdown so a soldier's
    unit-total denominator (W_i) for a given quarter doesn't depend on which
    other soldiers happen to be in the same batch/call.

    Without this, a two-branch floor (global default + this soldier's own
    date) can still miss a THIRD branch's earlier override that falls inside
    the same quarter — silently excluding that branch's duty from the
    quarter's unit total for every other soldier's breakdown, even though a
    batch compute_effort_data() call that happened to include that branch
    would have picked it up. Malformed override values are skipped rather
    than raising, since this sits on the live solve path."""
    overrides = _reset_date_overrides(session)
    earliest = _burden_share_reset_date(session)
    for raw in overrides.values():
        try:
            parsed = date.fromisoformat(raw)
        except (TypeError, ValueError):
            continue
        if parsed < earliest:
            earliest = parsed
    return earliest


def resolve_reset_dates_for_soldiers(
    session: Session, soldiers: Sequence[Any]
) -> dict[uuid.UUID, date]:
    """Per-soldier effective fairness reset date: nearest-ancestor override
    from fairness.reset_date_overrides, else the global fairness.reset_date
    default. `soldiers` need `.id` and `.hierarchy_node_id` (works for both
    `Soldier` ORM rows and `SoldierInput`).

    One query for the distinct hierarchy nodes actually present among
    `soldiers` (not the whole tree), then each distinct node's ancestor walk
    runs once and is cached — O(distinct_nodes) resolutions, O(soldiers) dict
    lookups, regardless of how many soldiers share a node."""
    overrides = _reset_date_overrides(session)
    default = _burden_share_reset_date(session)

    distinct_node_ids = {s.hierarchy_node_id for s in soldiers if s.hierarchy_node_id is not None}
    node_path_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    if distinct_node_ids:
        node_path_map = {
            n.id: list(n.path_ids)
            for n in session.execute(
                select(HierarchyNode.id, HierarchyNode.path_ids).where(
                    HierarchyNode.id.in_(distinct_node_ids)
                )
            ).all()
        }

    node_resolved: dict[uuid.UUID, date] = {
        node_id: _resolve_reset_date_from_path(node_path_map.get(node_id, []), overrides, default)
        for node_id in distinct_node_ids
    }

    return {
        s.id: node_resolved.get(s.hierarchy_node_id, default)
        for s in soldiers
    }


def _burden_share_planning_start(session: Session) -> date:
    today = date.today()
    latest_published_end = session.execute(
        select(func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        return latest_published_end + timedelta(days=1)
    return today


def _burden_share_quarter_windows(
    session: Session, *, reset_date: date, planning_start: date, planning_end: date
) -> list[tuple[date, date, date]]:
    """Return (tracked_start, tracked_end, calendar_quarter_start) like effort_score legacy code."""
    from app.services.effort_score import quarter_end, quarter_start

    windows: list[tuple[date, date, date]] = []
    history_end = planning_start - timedelta(days=1)
    if history_end >= reset_date:
        q_s = quarter_start(reset_date)
        while q_s < planning_start:
            q_e = quarter_end(q_s)
            actual_start = max(q_s, reset_date)
            actual_end = min(q_e, history_end)
            windows.append((actual_start, actual_end, q_s))
            q_s = q_e + timedelta(days=1)

    min_future = planning_end + timedelta(days=1)
    # Server-side quarter expansion: at scale this scans every published
    # assignment beyond the planning horizon.
    future_rows = session.execute(
        text(
            """
            SELECT DISTINCT (date_trunc('quarter', gs))::date AS quarter_start
            FROM duty_assignments a
            CROSS JOIN LATERAL generate_series(
                date_trunc(
                    'quarter',
                    GREATEST(a.start_date, CAST(:reset_date AS date), CAST(:min_future AS date))
                ),
                a.end_date - INTERVAL '1 day',
                INTERVAL '3 months'
            ) gs
            WHERE a.status = 'published'
              AND a.end_date > :min_future
              AND a.end_date > :reset_date
            """
        ).bindparams(
            reset_date=reset_date,
            min_future=min_future,
        )
    ).all()
    for (quarter_start_value,) in future_rows:
        windows.append((quarter_start_value, quarter_end(quarter_start_value), quarter_start_value))
    return windows


def _projection_data_keys_for_soldiers(
    session: Session, soldier_ids: set[uuid.UUID]
) -> set[tuple[uuid.UUID, date]]:
    from app.services.score_projection import _projection_keys_for_soldiers

    return _projection_keys_for_soldiers(session, soldier_ids)


def _projection_bucket_rows_are_complete(rows: list[SoldierQuarterScoreProjection]) -> bool:
    from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION

    if not rows:
        return False
    aggregate_count = sum(1 for row in rows if row.duty_type_id is None)
    return aggregate_count <= 1 and all(
        row.projection_version == SCORE_PROJECTION_CANONICAL_VERSION for row in rows
    )


def _projection_state_is_complete(session: Session) -> bool:
    from app.services.score_projection import (
        SCORE_PROJECTION_CANONICAL_VERSION,
        SCORE_PROJECTION_STATE_KEY,
    )

    state = session.get(ScoreProjectionState, SCORE_PROJECTION_STATE_KEY)
    return (
        state is not None
        and state.backfill_complete is True
        and state.canonical_version == SCORE_PROJECTION_CANONICAL_VERSION
    )


def _fingerprint_list(fingerprint: dict[str, Any], key: str) -> list[dict[str, Any]] | None:
    value = fingerprint.get(key)
    if not isinstance(value, list):
        return None
    return value


def _projection_row_matches_fingerprint_metadata(row: SoldierQuarterScoreProjection) -> bool:
    fingerprint = row.source_fingerprint
    if not isinstance(fingerprint, dict):
        return False

    duty_rows = _fingerprint_list(fingerprint, "duty_rows")
    overrides = _fingerprint_list(fingerprint, "overrides")
    dismissals = _fingerprint_list(fingerprint, "dismissals")
    adjustments = _fingerprint_list(fingerprint, "adjustments")
    if duty_rows is None or overrides is None or dismissals is None or adjustments is None:
        return False

    try:
        if row.duty_type_id is None:
            adjustment_score = sum(
                (_q6(adjustment.get("delta")) for adjustment in adjustments),
                Decimal("0"),
            )
            return (
                duty_rows == []
                and _q6(row.effective_weighted_days) == Decimal("0.000000")
                and _q6(row.duty_score) == Decimal("0.000000")
                and _q6(row.adjustment_score) == _q6(adjustment_score)
                and row.raw_day_count == 0
            )

        expected_duty_type_id = str(row.duty_type_id)
        if any(str(duty_row.get("duty_type_id")) != expected_duty_type_id for duty_row in duty_rows):
            return False
        effective_weighted_days = sum(
            (_q6(duty_row.get("weighted_multiplier")) for duty_row in duty_rows),
            Decimal("0"),
        )
        duty_score = sum((_q6(duty_row.get("score")) for duty_row in duty_rows), Decimal("0"))
        return (
            row.raw_day_count == len(duty_rows)
            and _q6(row.effective_weighted_days) == _q6(effective_weighted_days)
            and _q6(row.duty_score) == _q6(duty_score)
            and _q6(row.adjustment_score) == Decimal("0.000000")
            and adjustments == []
        )
    except Exception:
        logger.exception(
            "score projection persisted fingerprint metadata proof failed",
            extra={
                "soldier_id": str(row.soldier_id),
                "quarter_start": str(row.quarter_start),
                "projection_row_id": str(row.id),
            },
        )
        return False


def _projection_bucket_rows_match_persisted_metadata(
    rows: list[SoldierQuarterScoreProjection],
) -> bool:
    return _projection_bucket_rows_are_complete(rows) and all(
        _projection_row_matches_fingerprint_metadata(row) for row in rows
    )


def _projection_bucket_matches_canonical(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date
) -> bool:
    from app.services.score_projection import (
        _canonical_bucket_summary,
        _persisted_bucket_summary,
    )

    try:
        persisted = _persisted_bucket_summary(
            session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
        )
        canonical = _canonical_bucket_summary(
            session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
        )
    except Exception:
        logger.exception(
            "score projection canonical bucket proof failed",
            extra={"soldier_id": str(soldier_id), "quarter_start": str(quarter_start_value)},
        )
        return False
    return persisted == canonical


def _mark_projection_key_current(
    session: Session, *, soldier_id: uuid.UUID, quarter_start_value: date
) -> None:
    dirty = session.execute(
        select(ScoreProjectionDirtyBucket).where(
            ScoreProjectionDirtyBucket.soldier_id == soldier_id,
            ScoreProjectionDirtyBucket.quarter_start == quarter_start_value,
        )
    ).scalar_one_or_none()
    if dirty is None:
        return
    now = _score_projection_now()
    dirty.status = "current"
    dirty.divergence = None
    dirty.refreshed_at = now
    dirty.updated_at = now
    session.flush()


def _quarter_totals_are_current(session: Session, quarter_starts: set[date]) -> bool:
    from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION

    if not quarter_starts:
        return True
    rows = session.execute(
        select(ScoreProjectionQuarterTotal).where(
            ScoreProjectionQuarterTotal.quarter_start.in_(quarter_starts)
        )
    ).scalars().all()
    by_quarter = {row.quarter_start: row for row in rows}
    return all(
        (row := by_quarter.get(quarter_start_value)) is not None
        and row.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
        for quarter_start_value in quarter_starts
    )


def _quarter_total_matches_canonical(session: Session, quarter_start_value: date) -> bool:
    from app.services.score_projection import (
        SCORE_PROJECTION_CANONICAL_VERSION,
        _projection_totals_from_buckets,
        project_all_buckets,
    )

    row = session.get(ScoreProjectionQuarterTotal, quarter_start_value)
    if row is None or row.projection_version != SCORE_PROJECTION_CANONICAL_VERSION:
        return False
    try:
        canonical = _projection_totals_from_buckets(
            project_all_buckets(session, quarter_starts={quarter_start_value})
        )
    except Exception:
        logger.exception(
            "score projection canonical quarter-total proof failed",
            extra={"quarter_start": str(quarter_start_value)},
        )
        return False
    return (
        row.raw_day_count == canonical.raw_day_count
        and _q6(row.effective_weighted_days) == _q6(canonical.effective_weighted_days)
        and _q6(row.duty_score) == _q6(canonical.duty_score)
        and _q6(row.adjustment_score) == _q6(canonical.adjustment_score)
        and _q6(row.total_score) == _q6(canonical.total_score)
    )


def _quarter_total_from_projection_rows(
    session: Session, *, quarter_start_value: date
) -> dict[str, Decimal | int]:
    rows = session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value
        )
    ).scalars().all()
    duty_score = sum((_q6(row.duty_score) for row in rows), Decimal("0"))
    adjustment_score = sum((_q6(row.adjustment_score) for row in rows), Decimal("0"))
    effective_weighted_days = sum(
        (_q6(row.effective_weighted_days) for row in rows), Decimal("0")
    )
    raw_day_count = sum(row.raw_day_count for row in rows)
    return {
        "raw_day_count": raw_day_count,
        "effective_weighted_days": _q6(effective_weighted_days),
        "duty_score": _q6(duty_score),
        "adjustment_score": _q6(adjustment_score),
        "total_score": _q6(duty_score + adjustment_score),
    }


def _projection_quarter_rows_match_persisted_metadata(
    session: Session, *, quarter_start_value: date
) -> bool:
    from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION

    rows = session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.quarter_start == quarter_start_value
        )
    ).scalars().all()
    return all(
        row.projection_version == SCORE_PROJECTION_CANONICAL_VERSION
        and _projection_row_matches_fingerprint_metadata(row)
        for row in rows
    )


def _quarter_total_matches_projection_rows(
    session: Session, *, quarter_start_value: date
) -> bool:
    from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION

    row = session.get(ScoreProjectionQuarterTotal, quarter_start_value)
    if row is None or row.projection_version != SCORE_PROJECTION_CANONICAL_VERSION:
        return False
    expected = _quarter_total_from_projection_rows(
        session, quarter_start_value=quarter_start_value
    )
    return (
        row.raw_day_count == expected["raw_day_count"]
        and _q6(row.effective_weighted_days) == expected["effective_weighted_days"]
        and _q6(row.duty_score) == expected["duty_score"]
        and _q6(row.adjustment_score) == expected["adjustment_score"]
        and _q6(row.total_score) == expected["total_score"]
    )


def _required_quarter_totals_match_projection_rows(
    session: Session,
    *,
    quarter_starts: set[date],
    recompute_for_quarters: set[date] | None = None,
) -> bool:
    """Ensure every required quarter has a current stored total.

    Read-path contract: writers keep quarter totals in step with the partition
    rows, so the read only verifies existence and version (indexed lookups) and
    recomputes a total from its rows when it is missing/stale or its quarter
    was just repaired. Numeric divergence checking lives in
    ``verify_quarter_totals_match_rows`` (revalidation worker / diagnostics).
    """
    if not quarter_starts:
        return True

    from app.services.score_projection import (
        SCORE_PROJECTION_CANONICAL_VERSION,
        _upsert_quarter_total,
    )

    recompute_for_quarters = set(recompute_for_quarters or set())
    total_rows = {
        row.quarter_start: row
        for row in session.execute(
            select(ScoreProjectionQuarterTotal).where(
                ScoreProjectionQuarterTotal.quarter_start.in_(quarter_starts)
            )
        ).scalars().all()
    }

    for quarter_start_value in sorted(quarter_starts):
        total_row = total_rows.get(quarter_start_value)
        if (
            total_row is None
            or total_row.projection_version != SCORE_PROJECTION_CANONICAL_VERSION
            or quarter_start_value in recompute_for_quarters
        ):
            _upsert_quarter_total(session, quarter_start_value=quarter_start_value)
    return True


def verify_quarter_totals_match_rows(
    session: Session, *, quarter_starts: set[date] | None = None
) -> bool:
    """Full numeric verification of stored quarter totals against partition rows.

    Not used on the read path; the revalidation worker and diagnostics call
    this. With no quarters given, verifies every stored total.
    """
    if quarter_starts is None:
        quarter_starts = {
            row
            for (row,) in session.execute(select(ScoreProjectionQuarterTotal.quarter_start)).all()
        }
    quarter_starts = set(quarter_starts)
    if not quarter_starts:
        return True

    sums_by_quarter: dict[date, tuple[Any, Any, Any, Any]] = {}
    for quarter_start_value, raw_sum, ewd_sum, duty_sum, adj_sum in session.execute(
        select(
            SoldierQuarterScoreProjection.quarter_start,
            func.sum(SoldierQuarterScoreProjection.raw_day_count),
            func.sum(SoldierQuarterScoreProjection.effective_weighted_days),
            func.sum(SoldierQuarterScoreProjection.duty_score),
            func.sum(SoldierQuarterScoreProjection.adjustment_score),
        )
        .where(SoldierQuarterScoreProjection.quarter_start.in_(quarter_starts))
        .group_by(SoldierQuarterScoreProjection.quarter_start)
    ).all():
        sums_by_quarter[quarter_start_value] = (
            raw_sum or 0,
            ewd_sum or Decimal("0"),
            duty_sum or Decimal("0"),
            adj_sum or Decimal("0"),
        )

    total_rows = {
        row.quarter_start: row
        for row in session.execute(
            select(ScoreProjectionQuarterTotal).where(
                ScoreProjectionQuarterTotal.quarter_start.in_(quarter_starts)
            )
        ).scalars().all()
    }

    def _close(left: Any, right: Any) -> bool:
        return abs(_q6(left) - _q6(right)) <= Decimal("0.000001")

    for quarter_start_value in sorted(quarter_starts):
        total_row = total_rows.get(quarter_start_value)
        if total_row is None:
            logger.warning(
                "score projection quarter total verification failed: total missing",
                extra={"quarter_start": str(quarter_start_value)},
            )
            return False
        sums = sums_by_quarter.get(quarter_start_value)
        expected_raw = int(sums[0]) if sums else 0
        expected_ewd = _q6(sums[1]) if sums else Decimal("0")
        expected_duty = _q6(sums[2]) if sums else Decimal("0")
        expected_adj = _q6(sums[3]) if sums else Decimal("0")
        if not (
            total_row.raw_day_count == expected_raw
            and _close(total_row.effective_weighted_days, expected_ewd)
            and _close(total_row.duty_score, expected_duty)
            and _close(total_row.adjustment_score, expected_adj)
            and _close(total_row.total_score, expected_duty + expected_adj)
        ):
            logger.warning(
                "score projection quarter total diverges from persisted rows",
                extra={"quarter_start": str(quarter_start_value)},
            )
            return False
    return True



def _soldier_totals_by_id(
    session: Session, soldier_ids: set[uuid.UUID]
) -> dict[uuid.UUID, SoldierScoreProjection]:
    if not soldier_ids:
        return {}
    rows = session.execute(
        select(SoldierScoreProjection).where(uuid_any("soldier_score_projection.soldier_id", soldier_ids))
    ).scalars().all()
    return {row.soldier_id: row for row in rows}


def _projected_soldier_total_from_rows(
    session: Session, *, soldier_id: uuid.UUID
) -> dict[str, Decimal | int]:
    from app.services.score_projection import _expected_soldier_totals_by_id

    want = _expected_soldier_totals_by_id(session, {soldier_id})[soldier_id]
    duty_score = _q6(want["duty_score"])
    adjustment_score = _q6(want["adjustment_score"])
    return {
        "duty_score": duty_score,
        "adjustment_score": adjustment_score,
        "cumulative_score": _q6(duty_score + adjustment_score),
        "shift_count": want["shift_count"],
    }


def _soldier_total_matches_projection_rows(session: Session, *, soldier_id: uuid.UUID) -> bool:
    from app.services.score_projection import SCORE_PROJECTION_CANONICAL_VERSION

    totals = _soldier_totals_by_id(session, {soldier_id})
    row = totals.get(soldier_id)
    if row is None or row.projection_version != SCORE_PROJECTION_CANONICAL_VERSION:
        return False
    expected = _projected_soldier_total_from_rows(session, soldier_id=soldier_id)
    return (
        _q6(row.duty_score) == expected["duty_score"]
        and _q6(row.adjustment_score) == expected["adjustment_score"]
        and _q6(row.cumulative_score) == expected["cumulative_score"]
        and row.shift_count == expected["shift_count"]
    )


def _refresh_required_soldier_totals(
    session: Session, *, soldier_ids: set[uuid.UUID]
) -> bool:
    from app.services.score_projection import (
        SCORE_PROJECTION_CANONICAL_VERSION,
        _expected_soldier_totals_by_id,
        _upsert_soldier_total,
    )

    if not soldier_ids:
        return True

    stored = _soldier_totals_by_id(session, soldier_ids)
    # Read-path contract: totals are trusted unless they are missing/stale or
    # a dirty/divergent marker implicates the soldier. The numeric comparison
    # (an aggregate over partition-row fingerprints) only runs for implicated
    # soldiers.
    missing_or_stale = [
        soldier_id
        for soldier_id in sorted(soldier_ids, key=str)
        if (row := stored.get(soldier_id)) is None
        or row.projection_version != SCORE_PROJECTION_CANONICAL_VERSION
    ]
    implicated = {
        row.soldier_id
        for row in session.execute(
            select(ScoreProjectionDirtyBucket.soldier_id).where(
                uuid_any("score_projection_dirty_buckets.soldier_id", soldier_ids),
                or_(
                    ScoreProjectionDirtyBucket.status == "dirty",
                    ScoreProjectionDirtyBucket.divergence.is_not(None),
                ),
            )
        ).all()
    }
    if not implicated:
        stale = missing_or_stale
    else:
        expected = _expected_soldier_totals_by_id(session, implicated)
        stale = list(missing_or_stale)
        for soldier_id in sorted(implicated, key=str):
            row = stored.get(soldier_id)
            want = expected[soldier_id]
            cumulative_want = _q6(want["duty_score"] + want["adjustment_score"])
            if (
                row is None
                or row.projection_version != SCORE_PROJECTION_CANONICAL_VERSION
                or _q6(row.duty_score) != _q6(want["duty_score"])
                or _q6(row.adjustment_score) != _q6(want["adjustment_score"])
                or _q6(row.cumulative_score) != cumulative_want
                or row.shift_count != want["shift_count"]
            ):
                if soldier_id not in missing_or_stale:
                    stale.append(soldier_id)

    for soldier_id in sorted(set(stale), key=str):
        try:
            _upsert_soldier_total(session, soldier_id=soldier_id)
        except Exception:
            logger.exception(
                "score projection soldier total rebuild failed during read",
                extra={"soldier_id": str(soldier_id)},
            )
            return False
        if not _soldier_total_matches_projection_rows(session, soldier_id=soldier_id):
            logger.warning(
                "score projection read fell back because a soldier total is incomplete",
                extra={"soldier_id": str(soldier_id)},
            )
            return False
    return True


def _ensure_projection_ready(
    session: Session,
    *,
    keys: set[tuple[uuid.UUID, date]],
    quarter_starts: set[date] | None = None,
    total_soldier_ids: set[uuid.UUID] | None = None,
    canonical_diagnostic_check: bool = False,
) -> bool:
    from app.services.score_projection import (
        projection_is_current,
        rebuild_projection_bucket,
    )

    quarter_starts = set(quarter_starts or set())
    total_soldier_ids = set(total_soldier_ids or set())
    if (keys or quarter_starts or total_soldier_ids) and not _projection_state_is_complete(session):
        logger.warning("score projection read fell back because projection backfill is incomplete")
        return False

    rebuild_keys: set[tuple[uuid.UUID, date]] = set()
    from app.services.score_projection import (
        _bucket_health_counts,
        _dirty_or_divergent_projection_keys,
        _unhealthy_bucket_keys_detailed,
    )

    # Read-path contract: writers mark buckets dirty before rebuilding and
    # clear the marker after, so a clean marker table means every stored bucket
    # is exactly what its writer computed. Reads therefore run one cheap
    # structural health aggregate and rebuild what it or the markers flag; the
    # JSONB fingerprint proof runs periodically in the revalidation worker.
    key_soldiers = {soldier_id for soldier_id, _quarter_start_value in keys}
    dup_groups, stale_rows = (
        _bucket_health_counts(session, soldier_ids=key_soldiers) if key_soldiers else (0, 0)
    )
    if dup_groups or stale_rows:
        rebuild_keys |= _unhealthy_bucket_keys_detailed(session, soldier_ids=key_soldiers)

    if canonical_diagnostic_check:
        for soldier_id, quarter_start_value in sorted(keys, key=lambda item: (str(item[0]), item[1])):
            if not _projection_bucket_matches_canonical(
                session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
            ):
                logger.warning(
                    "score projection diagnostic canonical bucket comparison diverged",
                    extra={"soldier_id": str(soldier_id), "quarter_start": str(quarter_start_value)},
                )
                return False

    rebuild_keys.update(
        _dirty_or_divergent_projection_keys(
            session,
            soldier_ids=key_soldiers | total_soldier_ids,
        )
    )

    repaired_quarters: set[date] = set()
    for soldier_id, quarter_start_value in sorted(rebuild_keys, key=lambda item: (str(item[0]), item[1])):
        try:
            rebuild_projection_bucket(
                session, soldier_id, quarter_start_value, refresh_quarter_total=False
            )
            _mark_projection_key_current(
                session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
            )
            repaired_quarters.add(quarter_start_value)
        except Exception:
            logger.exception(
                "score projection bucket rebuild failed during read",
                extra={"soldier_id": str(soldier_id), "quarter_start": str(quarter_start_value)},
            )
            return False

    if repaired_quarters:
        from app.services.score_projection import _upsert_quarter_total

        # Repairing a bucket can change its partition rows (e.g. dropping an
        # adjustments-only row that no longer belongs to this quarter); the
        # quarter total must track the repaired rows.
        for quarter_start_value in sorted(repaired_quarters):
            _upsert_quarter_total(session, quarter_start_value=quarter_start_value)

    required: set[Any] = set(keys) | set(quarter_starts)
    if not projection_is_current(session, required):
        logger.warning("score projection read fell back because required buckets are not current")
        return False
    if rebuild_keys and (key_soldiers and (dup_groups or stale_rows)):
        dup_after, stale_after = _bucket_health_counts(session, soldier_ids=key_soldiers)
        if dup_after or stale_after:
            logger.warning("score projection read fell back because required buckets are incomplete")
            return False
    if quarter_starts and not _required_quarter_totals_match_projection_rows(
        session,
        quarter_starts=quarter_starts,
        recompute_for_quarters=repaired_quarters,
    ):
        return False
    if canonical_diagnostic_check:
        if keys and not all(
            _projection_bucket_matches_canonical(
                session, soldier_id=soldier_id, quarter_start_value=quarter_start_value
            )
            for soldier_id, quarter_start_value in keys
        ):
            logger.warning("score projection diagnostic canonical bucket comparison diverged")
            return False
        if quarter_starts and not all(
            _quarter_total_matches_canonical(session, quarter_start_value)
            for quarter_start_value in quarter_starts
        ):
            logger.warning("score projection diagnostic canonical quarter-total comparison diverged")
            return False
    if total_soldier_ids and not _refresh_required_soldier_totals(
        session, soldier_ids=total_soldier_ids
    ):
        return False
    return True


def _projection_burden_share_inputs(
    session: Session,
    *,
    soldiers: list[Soldier],
    reset_date: date,
    planning_start: date,
    planning_end: date,
) -> tuple[
    list[tuple[date, date, date]],
    dict[date, Decimal],
    dict[date, dict[uuid.UUID, Decimal]],
] | None:
    from app.services.effort_score import quarter_start

    # Persisted buckets are calendar-quarter aggregates. A reset date inside a
    # quarter needs day-level clipping, so keep legacy for that rare setting.
    if reset_date != quarter_start(reset_date):
        logger.warning("score projection read fell back because reset_date is not quarter-aligned")
        return None

    windows = _burden_share_quarter_windows(
        session, reset_date=reset_date, planning_start=planning_start, planning_end=planning_end
    )
    if not windows:
        return [], {}, {}

    soldier_ids = {soldier.id for soldier in soldiers}
    quarter_starts = {calendar_qs for _q_start, _q_end, calendar_qs in windows}
    keys = {
        key
        for key in _projection_data_keys_for_soldiers(session, soldier_ids)
        if key[1] in quarter_starts
    }
    if not _ensure_projection_ready(session, keys=keys, quarter_starts=quarter_starts):
        return None

    totals = {
        row.quarter_start: _q6(row.total_score)
        for row in session.execute(
            select(ScoreProjectionQuarterTotal).where(
                ScoreProjectionQuarterTotal.quarter_start.in_(quarter_starts)
            )
        ).scalars().all()
    }
    soldier_scores: dict[date, dict[uuid.UUID, Decimal]] = defaultdict(dict)
    projection_rows = session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id.in_(soldier_ids),
            SoldierQuarterScoreProjection.quarter_start.in_(quarter_starts),
        )
    ).scalars().all()
    grouped: dict[tuple[uuid.UUID, date], Decimal] = defaultdict(lambda: Decimal("0"))
    for row in projection_rows:
        grouped[(row.soldier_id, row.quarter_start)] += _q6(row.duty_score) + _q6(row.adjustment_score)
    for (soldier_id, quarter_start_value), score in grouped.items():
        soldier_scores[quarter_start_value][soldier_id] = _q6(score)
    return windows, totals, dict(soldier_scores)


def _try_projected_effort_data(
    session: Session, soldiers: list[Soldier]
) -> dict[uuid.UUID, Any] | None:
    from app.services.effort_score import _compute_effort_data

    reset_date = _burden_share_reset_date(session)
    soldier_reset_dates = resolve_reset_dates_for_soldiers(session, soldiers)
    if any(d != reset_date for d in soldier_reset_dates.values()):
        return None  # a hierarchy override applies to at least one soldier; the
                      # cache's precomputed windows assume one global date — defer
                      # to compute_effort_data's live, override-aware recompute.
    planning_start = _burden_share_planning_start(session)
    projection_inputs = _projection_burden_share_inputs(
        session,
        soldiers=soldiers,
        reset_date=reset_date,
        planning_start=planning_start,
        planning_end=planning_start,
    )
    if projection_inputs is None:
        return None
    windows, q_unit_scores, q_soldier_scores = projection_inputs
    data = _compute_effort_data(
        soldiers=soldiers,
        quarters=[(q_start, q_end) for q_start, q_end, _calendar_qs in windows],
        quarter_unit_scores={
            q_start: q_unit_scores.get(calendar_qs, Decimal("0"))
            for q_start, _q_end, calendar_qs in windows
        },
        quarter_soldier_scores={
            q_start: q_soldier_scores.get(calendar_qs, {})
            for q_start, _q_end, calendar_qs in windows
        },
        soldier_reset_dates=soldier_reset_dates,
    )
    return data


def _try_projected_burden_shares(
    session: Session, soldiers: list[Soldier]
) -> dict[uuid.UUID, float] | None:
    data = _try_projected_effort_data(session, soldiers)
    if data is None:
        return None
    return {sid: float(item.effort_score) for sid, item in data.items()}


def _try_projected_burden_share_breakdown(
    session: Session,
    *,
    soldier: Any,
    planning_start: date,
    planning_end: date,
    reset_date: date,
    extra_adj_delta: Decimal = Decimal("0"),
    extra_adj_date: date | None = None,
) -> Any | None:
    from app.services.effort_score import (
        BurdenShareBreakdown,
        BurdenShareQuarterDetail,
        _quarter_label,
        quarter_end,
        quarter_start,
    )

    if reset_date != quarter_start(reset_date):
        logger.warning("effort breakdown fell back because reset_date is not quarter-aligned")
        return None

    resolved = resolve_reset_dates_for_soldiers(session, [soldier])[soldier.id]
    if resolved != reset_date:
        return None

    windows = _burden_share_quarter_windows(
        session, reset_date=reset_date, planning_start=planning_start, planning_end=planning_end
    )
    if not windows:
        return BurdenShareBreakdown(quarters=[], burden_share=Decimal("0"), A_i=Decimal("0"), W_i=Decimal("0"))

    quarter_starts = {calendar_qs for _q_start, _q_end, calendar_qs in windows}
    keys = {
        key
        for key in _projection_data_keys_for_soldiers(session, {soldier.id})
        if key[1] in quarter_starts
    }
    if not _ensure_projection_ready(session, keys=keys, quarter_starts=quarter_starts):
        return None

    quarter_totals = {
        row.quarter_start: row
        for row in session.execute(
            select(ScoreProjectionQuarterTotal).where(
                ScoreProjectionQuarterTotal.quarter_start.in_(quarter_starts)
            )
        ).scalars().all()
    }
    q_unit_scores: dict[date, Decimal] = {
        quarter_start_value: _q6(total.duty_score)
        for quarter_start_value, total in quarter_totals.items()
    }
    q_soldier_scores: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    q_adj_scores: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    rows = session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier.id,
            SoldierQuarterScoreProjection.quarter_start.in_(quarter_starts),
        )
    ).scalars().all()
    for row in rows:
        q_soldier_scores[row.quarter_start] += _q6(row.duty_score) + _q6(row.adjustment_score)
        q_adj_scores[row.quarter_start] += _q6(row.adjustment_score)

    # Legacy compute_burden_share_breakdown includes this soldier's adjustments in the
    # displayed unit score, not every soldier's adjustments. Keep that contract.
    for quarter_start_value, adjustment_score in q_adj_scores.items():
        q_unit_scores[quarter_start_value] = q_unit_scores.get(quarter_start_value, Decimal("0")) + adjustment_score

    if extra_adj_delta and extra_adj_date is not None:
        extra_qs = quarter_start(extra_adj_date)
        if extra_qs in quarter_starts:
            delta = Decimal(extra_adj_delta)
            q_adj_scores[extra_qs] += delta
            q_unit_scores[extra_qs] = q_unit_scores.get(extra_qs, Decimal("0")) + delta
            q_soldier_scores[extra_qs] += delta

    quarter_details: list[BurdenShareQuarterDetail] = []
    A_i = Decimal("0")
    W_i = Decimal("0")
    for q_start_d, q_end_d, calendar_qs in windows:
        q_days = (q_end_d - q_start_d).days + 1
        soldier_start = max(soldier.unit_join_date or soldier.enrolled_at, q_start_d)
        if soldier_start > q_end_d:
            continue

        active_in_q = (q_end_d - soldier_start).days + 1
        active_frac = Decimal(active_in_q) / Decimal(q_days)
        unit_score = q_unit_scores.get(calendar_qs, Decimal("0"))
        s_score = q_soldier_scores.get(calendar_qs, Decimal("0"))
        share = s_score / unit_score if unit_score > 0 else Decimal("0")
        weighted_share = share * active_frac

        if unit_score > 0:
            A_i += s_score * active_frac
            W_i += unit_score * active_frac

        true_q_end = quarter_end(q_start_d)
        quarter_details.append(
            BurdenShareQuarterDetail(
                quarter_start=q_start_d,
                quarter_end=q_end_d,
                quarter_label=_quarter_label(q_start_d),
                soldier_score=s_score,
                unit_score=unit_score,
                active_frac=active_frac,
                share=share,
                weighted_share=weighted_share,
                is_partial=(q_end_d < true_q_end),
                adjustment_delta=q_adj_scores.get(calendar_qs, Decimal("0")),
            )
        )

    burden_share = A_i / W_i if W_i > Decimal("0") else Decimal("0")

    if quarter_details:
        from app.services.effort_score import compute_quarter_contributions, quarter_start as _qstart

        contrib_map = compute_quarter_contributions(
            session,
            soldier_id=soldier.id,
            quarters={_qstart(d.quarter_start) for d in quarter_details},
        )
        for d in quarter_details:
            d.contributions = contrib_map.get(_qstart(d.quarter_start), [])

    return BurdenShareBreakdown(quarters=quarter_details, burden_share=burden_share, A_i=A_i, W_i=W_i)


def burden_shares_by_soldier(
    session: Session, soldiers: list[Soldier]
) -> dict[uuid.UUID, float]:
    """Burden share (scale-invariant A_i/W_i ratio) per soldier id, using the
    same reset-date/planning-horizon rules as the transparency page."""
    projected = _try_projected_burden_shares(session, soldiers)
    if projected is not None:
        return projected

    from app.services.effort_score import compute_effort_data

    today = date.today()

    from sqlalchemy import func as sql_func
    latest_published_end = session.execute(
        select(sql_func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        planning_start = latest_published_end + timedelta(days=1)
    else:
        planning_start = today

    effort_map = compute_effort_data(
        session,
        soldiers=soldiers,
        planning_start=planning_start,
        planning_end=planning_start,
    )
    return {sid: float(data.effort_score) for sid, data in effort_map.items()}


def _try_projected_transparency_rows(
    session: Session, *, viewer: Soldier | None = None
) -> dict[str, Any] | None:
    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    soldier_ids = {soldier.id for soldier in soldiers}
    reset_date = _burden_share_reset_date(session)
    planning_start = _burden_share_planning_start(session)
    effort_windows = _burden_share_quarter_windows(
        session,
        reset_date=reset_date,
        planning_start=planning_start,
        planning_end=planning_start,
    )
    effort_quarters = {calendar_qs for _q_start, _q_end, calendar_qs in effort_windows}
    keys = _projection_data_keys_for_soldiers(session, soldier_ids)
    score_quarters = {quarter_start_value for _soldier_id, quarter_start_value in keys}
    if not _ensure_projection_ready(
        session,
        keys=keys,
        quarter_starts=score_quarters | effort_quarters,
        total_soldier_ids=soldier_ids,
    ):
        return None

    total_rows = session.execute(
        select(SoldierScoreProjection).where(uuid_any("soldier_score_projection.soldier_id", soldier_ids))
    ).scalars().all()
    totals_by_soldier = {row.soldier_id: row for row in total_rows}
    active_days_map = _bulk_active_days(session, list(soldiers))
    nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    exempted_ids = globally_exempted_soldier_ids(session)
    exemptions_by_soldier = _active_exemptions_by_soldier(session)
    roots = scope_root_ids(session, viewer) if viewer is not None else set()
    can_see_exemption_aggregates = viewer is not None and (
        viewer.role == "admin" or bool(roots)
    )
    effort_map = _try_projected_effort_data(session, list(soldiers))
    if effort_map is None:
        return None

    rows: list[dict[str, Any]] = []
    population_spd: list[Decimal] = []
    for s in soldiers:
        node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        total = totals_by_soldier.get(s.id)
        if total is None:
            logger.warning(
                "score projection read fell back because a soldier total is missing",
                extra={"soldier_id": str(s.id)},
            )
            return None
        cum = _q6(total.cumulative_score)
        shift_count = total.shift_count
        ad = active_days_map.get(s.id, 1)
        # Normalisation is computed over the FULL active population (dev
        # behavior) regardless of which rows this viewer may see.
        population_spd.append(cum / Decimal(ad))
        if viewer is not None and s.id != viewer.id and viewer.role != "admin" and not can_view_soldier_scope(session, viewer, node):
            continue
        soldier_exemptions = exemptions_by_soldier.get(s.id, [])
        in_scope = node is not None and any(root in node.path_ids for root in roots)
        if in_scope:
            exemptions_display = ", ".join(
                _exemption_label(exemption, ex_type) for exemption, ex_type in soldier_exemptions
            )
            exemptions_summary = [
                {
                    "id": exemption.id,
                    "exemption_type_name": ex_type.name,
                    "is_global": ex_type.is_global,
                    "start_date": exemption.start_date,
                    "end_date": exemption.end_date,
                }
                for exemption, ex_type in soldier_exemptions
            ]
        else:
            exemptions_display = "חסוי"
            exemptions_summary = []
        has_global = any(ex_type.is_global for _, ex_type in soldier_exemptions)
        has_partial = any(not ex_type.is_global for _, ex_type in soldier_exemptions)
        has_temporary = any(exemption.end_date is not None for exemption, _ in soldier_exemptions)
        effort_data = effort_map.get(s.id)
        burden_share = float(effort_data.effort_score) if effort_data else 0.0
        c_over_d = float(effort_data.C_over_D) if effort_data else 0.0
        burden_share_offset_raw = effort_data.effort_offset if effort_data else 0
        rows.append(
            {
                "soldier_id": s.id,
                "full_name": s.full_name,
                "node_id": s.hierarchy_node_id,
                "node_name": node.name if node is not None else None,
                "enrolled_at": s.enrolled_at,
                "active_days": ad,
                "shift_count": shift_count,
                "rank": s.rank,
                "is_officer": s.is_officer,
                "service_type": inferred_service_type(s),
                "cumulative_score": cum,
                "score_per_day": cum / Decimal(ad),
                "is_globally_exempted": s.id in exempted_ids,
                "exemptions_display": exemptions_display,
                "exemptions_visible": in_scope,
                "exemptions": exemptions_summary,
                "has_global_exemption": has_global if can_see_exemption_aggregates else None,
                "has_partial_exemption": has_partial if can_see_exemption_aggregates else None,
                "has_temporary_exemption": has_temporary if can_see_exemption_aggregates else None,
                "burden_share": burden_share,
                "c_over_d": c_over_d,
                "burden_share_offset_raw": burden_share_offset_raw,
            }
        )
    if population_spd:
        avg_spd = sum(population_spd) / Decimal(len(population_spd))
    else:
        avg_spd = Decimal("0")
    for r in rows:
        r["normalised_score"] = (
            r["score_per_day"] / avg_spd if avg_spd != Decimal("0") else Decimal("0")
        )
    rows.sort(key=lambda r: r["burden_share"], reverse=True)
    return {
        "rows": rows,
        "can_see_exemption_aggregates": can_see_exemption_aggregates,
        "population_count": len(soldiers),
    }


def transparency_rows(
    session: Session, *, viewer: Soldier | None = None
) -> dict[str, Any]:
    # Both projected and legacy builders preserve the public "burden_share" key.
    projected = _try_projected_transparency_rows(session, viewer=viewer)
    if projected is not None:
        return projected
    logger.warning("transparency scoring read fell back to legacy calculation")
    return _legacy_transparency_rows(session, viewer=viewer)


def _legacy_transparency_rows(
    session: Session, *, viewer: Soldier | None = None
) -> dict[str, Any]:
    from app.services.effort_score import compute_effort_data, quarter_start
    from app.services.settings_loader import SettingNotFound, get_setting

    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    duty_scores, shift_counts = _duty_stats_by_soldier(session)
    adj_scores = adjustments_by_soldier(session)
    active_days_map = _bulk_active_days(session, list(soldiers))
    nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    exempted_ids = globally_exempted_soldier_ids(session)
    exemptions_by_soldier = _active_exemptions_by_soldier(session)
    roots = scope_root_ids(session, viewer) if viewer is not None else set()
    can_see_exemption_aggregates = viewer is not None and (
        viewer.role == "admin" or bool(roots)
    )

    # Compute effort scores for all active soldiers
    today = date.today()

    # Include future published assignments by using the day after the latest
    # published assignment as the planning horizon.  Without this, effort_score
    # is always 0 when all assignments are for upcoming dates.
    from sqlalchemy import func as sql_func
    latest_published_end = session.execute(
        select(sql_func.max(DutyAssignment.end_date)).where(DutyAssignment.status == "published")
    ).scalar()
    if latest_published_end is not None and latest_published_end >= today:
        planning_start = latest_published_end + timedelta(days=1)
    else:
        planning_start = today

    effort_map = compute_effort_data(
        session,
        soldiers=list(soldiers),
        planning_start=planning_start,
        planning_end=planning_start,
    )

    rows: list[dict[str, Any]] = []
    population_spd: list[Decimal] = []
    for s in soldiers:
        node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))
        ad = active_days_map.get(s.id, 1)
        # Normalisation is computed over the FULL active population (dev
        # behavior) regardless of which rows this viewer may see.
        population_spd.append(cum / Decimal(ad))
        if viewer is not None and s.id != viewer.id and viewer.role != "admin" and not can_view_soldier_scope(session, viewer, node):
            continue
        soldier_exemptions = exemptions_by_soldier.get(s.id, [])
        in_scope = node is not None and any(root in node.path_ids for root in roots)
        if in_scope:
            exemptions_display = ", ".join(
                _exemption_label(exemption, ex_type) for exemption, ex_type in soldier_exemptions
            )
            exemptions_summary = [
                {
                    "id": exemption.id,
                    "exemption_type_name": ex_type.name,
                    "is_global": ex_type.is_global,
                    "start_date": exemption.start_date,
                    "end_date": exemption.end_date,
                }
                for exemption, ex_type in soldier_exemptions
            ]
        else:
            exemptions_display = "חסוי"
            exemptions_summary = []
        has_global = any(ex_type.is_global for _, ex_type in soldier_exemptions)
        has_partial = any(not ex_type.is_global for _, ex_type in soldier_exemptions)
        has_temporary = any(exemption.end_date is not None for exemption, _ in soldier_exemptions)
        effort_data = effort_map.get(s.id)
        burden_share = float(effort_data.effort_score) if effort_data else 0.0
        c_over_d = float(effort_data.C_over_D) if effort_data else 0.0
        burden_share_offset_raw = effort_data.effort_offset if effort_data else 0
        rows.append(
            {
                "soldier_id": s.id,
                "full_name": s.full_name,
                "node_id": s.hierarchy_node_id,
                "node_name": node.name if node is not None else None,
                "enrolled_at": s.enrolled_at,
                "active_days": ad,
                "shift_count": shift_counts.get(s.id, 0),
                "rank": s.rank,
                "is_officer": s.is_officer,
                "service_type": inferred_service_type(s),
                "cumulative_score": cum,
                "score_per_day": cum / Decimal(ad),
                "is_globally_exempted": s.id in exempted_ids,
                "exemptions_display": exemptions_display,
                "exemptions_visible": in_scope,
                "exemptions": exemptions_summary,
                "has_global_exemption": has_global if can_see_exemption_aggregates else None,
                "has_partial_exemption": has_partial if can_see_exemption_aggregates else None,
                "has_temporary_exemption": has_temporary if can_see_exemption_aggregates else None,
                "burden_share": burden_share,
                "c_over_d": c_over_d,
                "burden_share_offset_raw": burden_share_offset_raw,
            }
        )
    if population_spd:
        avg_spd = sum(population_spd) / Decimal(len(population_spd))
    else:
        avg_spd = Decimal("0")
    for r in rows:
        r["normalised_score"] = (
            r["score_per_day"] / avg_spd if avg_spd != Decimal("0") else Decimal("0")
        )
    rows.sort(key=lambda r: r["burden_share"], reverse=True)
    return {
        "rows": rows,
        "can_see_exemption_aggregates": can_see_exemption_aggregates,
        "population_count": len(soldiers),
    }


def _try_projected_soldier_score_breakdown(
    session: Session, *, soldier_id: uuid.UUID
) -> dict[str, Any] | None:
    keys = _projection_data_keys_for_soldiers(session, {soldier_id})
    if keys and not _ensure_projection_ready(session, keys=keys):
        return None

    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    rows = session.execute(
        select(SoldierQuarterScoreProjection).where(
            SoldierQuarterScoreProjection.soldier_id == soldier_id
        )
    ).scalars().all()

    today = date.today()
    per_type_data: dict[uuid.UUID, dict[str, Any]] = {}
    for row in rows:
        if row.duty_type_id is None:
            continue
        entry = per_type_data.setdefault(
            row.duty_type_id,
            {
                "duty_type_id": row.duty_type_id,
                "duty_type_name": dt_names.get(row.duty_type_id),
                "days": 0,
                "days_past": 0,
                "days_future": 0,
                "score": Decimal("0"),
            },
        )
        entry["score"] += _q6(row.duty_score)
        for duty_row in row.source_fingerprint.get("duty_rows", []):
            day_raw = duty_row.get("day")
            day = date.fromisoformat(day_raw) if isinstance(day_raw, str) else day_raw
            if day is None:
                continue
            entry["days"] += 1
            if day <= today:
                entry["days_past"] += 1
            else:
                entry["days_future"] += 1

    adjustments = (
        session.execute(
            select(ScoreAdjustment)
            .where(ScoreAdjustment.soldier_id == soldier_id)
            .order_by(ScoreAdjustment.created_at)
        )
        .scalars()
        .all()
    )
    return {"per_type": list(per_type_data.values()), "adjustments": list(adjustments)}


def soldier_score_breakdown(session: Session, *, soldier_id: uuid.UUID) -> dict[str, Any]:
    projected = _try_projected_soldier_score_breakdown(session, soldier_id=soldier_id)
    if projected is not None:
        return projected
    logger.warning(
        "single-soldier score breakdown fell back to legacy calculation",
        extra={"soldier_id": str(soldier_id)},
    )
    return _legacy_soldier_score_breakdown(session, soldier_id=soldier_id)


def _legacy_soldier_score_breakdown(session: Session, *, soldier_id: uuid.UUID) -> dict[str, Any]:
    scores = _duty_type_scores(session)
    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    by_type: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    days_past_by_type: dict[uuid.UUID, int] = defaultdict(int)
    days_future_by_type: dict[uuid.UUID, int] = defaultdict(int)
    today = date.today()
    for day, eff, dtid, mult in effective_duty_days(session):
        if eff == soldier_id:
            by_type[dtid] += scores.get(dtid, Decimal("0")) * mult
            if day <= today:
                days_past_by_type[dtid] += 1
            else:
                days_future_by_type[dtid] += 1
    per_type = [
        {
            "duty_type_id": dtid,
            "duty_type_name": dt_names.get(dtid),
            "days": days_past_by_type[dtid] + days_future_by_type[dtid],
            "days_past": days_past_by_type[dtid],
            "days_future": days_future_by_type[dtid],
            "score": score,
        }
        for dtid, score in by_type.items()
    ]
    adjustments = (
        session.execute(
            select(ScoreAdjustment)
            .where(ScoreAdjustment.soldier_id == soldier_id)
            .order_by(ScoreAdjustment.created_at)
        )
        .scalars()
        .all()
    )
    return {"per_type": per_type, "adjustments": list(adjustments)}


def _burden_share_stats(values: list[float]) -> dict[str, Any] | None:
    """mean / stddev / cv / min / max for a list of effort scores (population stddev)."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    sd = var ** 0.5
    return {
        "mean": mean, "stddev": sd, "cv": (sd / mean if mean else 0.0),
        "min": min(values), "max": max(values), "count": len(values),
    }


def _build_fairness_components(
    eligible_types: dict[uuid.UUID, set[uuid.UUID]],
    type_names: dict[uuid.UUID, str],
    burden_share_by_id: dict[uuid.UUID, float],
    name_by_id: dict[uuid.UUID, str],
    soldier_eligible_types: dict[uuid.UUID, set[uuid.UUID]] | None = None,
) -> dict[str, Any]:
    """Group soldiers into connected components of the soldier↔duty-type eligibility
    graph: two soldiers connect if they share a doable duty type (transitively).
    Soldiers eligible for no active type go in the 'exempt_from_all' bucket. Each
    component reports the duty types that connect it and its burden-share spread (פיזור)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    exempt_all: list[uuid.UUID] = []
    for sid, elig in eligible_types.items():
        if not elig:
            exempt_all.append(sid)
            continue
        snode = f"s:{sid}"
        find(snode)
        for tid in elig:
            union(snode, f"t:{tid}")

    groups: dict[str, dict[str, Any]] = {}
    for sid, elig in eligible_types.items():
        if not elig:
            continue
        g = groups.setdefault(find(f"s:{sid}"), {"soldiers": [], "type_ids": set()})
        g["soldiers"].append(sid)
        g["type_ids"].update(elig)

    elig = soldier_eligible_types or eligible_types

    def soldier_obj(sid: uuid.UUID, component_type_ids: set[uuid.UUID] | None = None) -> dict[str, Any]:
        eligible_count = len(elig.get(sid, set()) & component_type_ids) if component_type_ids is not None else 0
        return {"soldier_id": sid, "full_name": name_by_id.get(sid, ""),
                "burden_share": burden_share_by_id.get(sid, 0.0),
                "eligible_type_count": eligible_count}

    components = []
    for g in groups.values():
        shares = [burden_share_by_id.get(sid, 0.0) for sid in g["soldiers"]]
        comp_type_ids: set[uuid.UUID] = g["type_ids"]
        components.append({
            "duty_type_ids": sorted(str(tid) for tid in comp_type_ids),
            "duty_type_names": sorted(type_names[tid] for tid in comp_type_ids if tid in type_names),
            "soldier_count": len(g["soldiers"]),
            "burden_share": _burden_share_stats(shares),
            "soldiers": sorted((soldier_obj(s, comp_type_ids) for s in g["soldiers"]),
                               key=lambda o: o["burden_share"], reverse=True),
        })
    components.sort(key=lambda c: c["soldier_count"], reverse=True)

    return {
        "exempt_from_all": {
            "count": len(exempt_all),
            "soldiers": sorted((soldier_obj(s) for s in exempt_all),
                               key=lambda o: o["full_name"]),
        },
        "components": components,
    }


def _soldier_burden_share(built: dict[str, Any], soldier_id: uuid.UUID) -> dict[str, Any] | None:
    """Anonymized rank/spread summary for one soldier, derived from an already-built
    _build_fairness_components() result. Carries no other soldier's identity — only
    the peer effort-score values, for drawing a distribution without exposing names.
    Returns None if the soldier is exempt from every duty type (no group to compare against)."""
    for c in built["components"]:
        for idx, s in enumerate(c["soldiers"]):
            if s["soldier_id"] == soldier_id:
                stats = c["burden_share"]
                return {
                    "burden_share": s["burden_share"],
                    "rank": idx + 1,
                    "group_size": c["soldier_count"],
                    "duty_type_names": c["duty_type_names"],
                    "peer_scores": [o["burden_share"] for o in c["soldiers"]],
                    "mean": stats["mean"] if stats else None,
                    "stddev": stats["stddev"] if stats else None,
                    "cv": stats["cv"] if stats else None,
                    "low_sample": c["soldier_count"] < 3,
                }
    return None


def soldier_burden_share(session: Session, soldier_id: uuid.UUID) -> dict[str, Any] | None:
    """Anonymized rank + spread for one soldier within their duty-type eligibility
    component, computed org-wide (unscoped by viewer visibility, since the result
    carries no other soldier's identity — see _soldier_burden_share)."""
    from app.services.algorithm_bridge import exempted_duty_type_ids_by_soldier

    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    burden_share_by_id = burden_shares_by_soldier(session, soldiers)

    active_type_ids = _active_duty_type_ids(session)
    type_names = {
        dt.id: dt.name
        for dt in session.execute(
            select(DutyType).where(DutyType.id.in_(active_type_ids))
        ).scalars().all()
    }
    exempt_map = exempted_duty_type_ids_by_soldier(session, as_of=date.today())
    eligible_types = {
        s.id: (active_type_ids - exempt_map.get(s.id, set()))
        for s in soldiers
    }
    built = _build_fairness_components(eligible_types, type_names, burden_share_by_id, {}, soldier_eligible_types=eligible_types)
    return _soldier_burden_share(built, soldier_id)


def fairness_components(session: Session, *, viewer: Soldier | None = None) -> dict[str, Any]:
    """Burden-share spread (פיזור) split by connected components of soldiers who share
    duty-type eligibility, plus the soldiers exempt from every active duty type.
    Soldier lists are scoped to what `viewer` may see (see can_view_soldier_scope)."""
    from app.services.algorithm_bridge import load_soldier_inputs

    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    visible_soldiers = [
        soldier
        for soldier in soldiers
        if viewer is None
        or viewer.role == "admin"
        or can_view_soldier_scope(
            session,
            viewer,
            nodes.get(soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None,
        )
    ]
    visible_ids = {soldier.id for soldier in visible_soldiers}
    burden_share_by_id = burden_shares_by_soldier(session, visible_soldiers)
    name_by_id = {soldier.id: soldier.full_name for soldier in visible_soldiers}

    active_type_ids = _active_duty_type_ids(session)
    type_names = {
        dt.id: dt.name
        for dt in session.execute(
            select(DutyType).where(DutyType.id.in_(active_type_ids))
        ).scalars().all()
    }
    from app.services.algorithm_bridge import exempted_duty_type_ids_by_soldier

    exempt_map = exempted_duty_type_ids_by_soldier(session, as_of=date.today())
    eligible_types = {
        soldier_id: (active_type_ids - exempt_map.get(soldier_id, set()))
        for soldier_id in visible_ids
    }
    return _build_fairness_components(eligible_types, type_names, burden_share_by_id, name_by_id, soldier_eligible_types=eligible_types)
