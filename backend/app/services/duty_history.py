# backend/app/services/duty_history.py
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    DutyAssignment,
    DutyDayOverride,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionRequest,
    ExemptionType,
    PersonalConstraint,
    RangeAssignment,
    RangeEvent,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeLocation,
    Soldier,
    SoldierExemption,
)


@dataclass
class TimelineEvent:
    id: uuid.UUID
    event_type: str
    date: str
    end_date: str | None
    title: str
    description: str | None
    status: str | None
    metadata: dict = field(default_factory=dict)
    created_at: str = ""


def _fmt(d: Decimal) -> str:
    """Format a Decimal in fixed notation with at least one decimal place.

    Examples: Decimal("3.000") -> "3.0", Decimal("0.600") -> "0.6",
              Decimal("1.300") -> "1.3", Decimal("0.000") -> "0.0"
    """
    n = d.normalize()
    _, _, exponent = n.as_tuple()
    if exponent >= 0:
        return str(int(n)) + ".0"
    return format(n, "f")


def _score_parts(
    a: "DutyAssignment",
    dismissal_ranges: list[tuple[date, date]],
    spd: Decimal,
    standby_mult: Decimal,
    called_up_mult: Decimal,
    dismissed_mult: Decimal,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[str, str, str]:
    """Return (score_total, score_formula, segments_json) for the given period.

    segments_json is a JSON array of {"days", "spd", "mult", "type"} objects.
    Returns ("0.0", "", "[]") when there are no days in range or spd is zero.
    """
    start = max(a.start_date, date_from) if date_from is not None else a.start_date
    # date_to is inclusive; convert to exclusive to match end_date semantics
    end = min(a.end_date, date_to + timedelta(days=1)) if date_to is not None else a.end_date

    if start >= end or spd == Decimal("0"):
        return "0.0", "", "[]"

    def _day_mult_and_type(day: date) -> tuple[Decimal, str]:
        if a.forced_call_up_multiplier is not None:
            return a.forced_call_up_multiplier, "forced_call_up"
        if any(df <= day <= dt for df, dt in dismissal_ranges):
            return dismissed_mult, "dismissed"
        if a.is_reserve:
            if (
                a.called_up_from is not None
                and a.called_up_to is not None
                and a.called_up_from <= day <= a.called_up_to
            ):
                return called_up_mult, "reserve_called_up"
            return standby_mult, "reserve_standby"
        return Decimal("1.0"), "regular"

    # Group consecutive days by (mult, seg_type)
    segments: list[tuple[int, Decimal, str]] = []
    cur_key: tuple[Decimal, str] | None = None
    cur_count = 0

    day = start
    while day < end:
        m, t = _day_mult_and_type(day)
        key = (m, t)
        if key == cur_key:
            cur_count += 1
        else:
            if cur_key is not None:
                segments.append((cur_count, cur_key[0], cur_key[1]))
            cur_key = key
            cur_count = 1
        day += timedelta(days=1)
    if cur_key is not None:
        segments.append((cur_count, cur_key[0], cur_key[1]))

    total: Decimal = sum(Decimal(str(count)) * spd * mult for count, mult, _ in segments)
    formula = " + ".join(
        f"{count} × {_fmt(spd)} × {_fmt(mult)}" for count, mult, _ in segments
    )
    segments_json = json.dumps([
        {"days": count, "spd": _fmt(spd), "mult": _fmt(mult), "type": seg_type}
        for count, mult, seg_type in segments
    ])
    return _fmt(total), formula, segments_json


def _isodate(d: date | None) -> str | None:
    return d.isoformat() if d else None


_RANGE_TYPE_HE: dict[str, str] = {
    "laser": "לייזר",
    "live": "חי",
    "alal": 'אל"ל',
}


def _range_type_he(range_type) -> str:
    """Hebrew label for a RangeType enum/str value."""
    value = getattr(range_type, "value", range_type)
    return _RANGE_TYPE_HE.get(value, value)


def get_duty_history(
    session: Session,
    soldier_id: uuid.UUID,
    include_drafts: bool = False,
    include_sensitive: bool = True,
) -> list[TimelineEvent]:
    from app.services.scoring import _get_multiplier_setting

    standby_mult = _get_multiplier_setting(
        session, "scoring.reserve_standby_multiplier", "0.2"
    )
    called_up_mult = _get_multiplier_setting(
        session, "scoring.reserve_called_up_multiplier", "1.3"
    )
    dismissed_mult = _get_multiplier_setting(
        session, "scoring.dismissed_multiplier", "0.0"
    )

    events: list[TimelineEvent] = []

    # --- DutyAssignment events (assignment & cancellation & call_up) ---
    excluded_statuses = ["algorithm_rejected"]
    if not include_drafts:
        excluded_statuses.append("algorithm_draft")

    assignments = list(
        session.execute(
            select(DutyAssignment).where(
                DutyAssignment.soldier_id == soldier_id,
                DutyAssignment.status.not_in(excluded_statuses),
            )
        ).scalars().all()
    )

    # Days this soldier received via a swap: the swap flow only ever writes
    # DutyDayOverride rows — it never mutates DutyAssignment.soldier_id — so
    # those days are invisible to the query above. Only keep overrides whose
    # owning assignment does NOT already belong to this soldier, to avoid
    # double-counting a soldier's own (un-swapped) days.
    override_rows = list(
        session.execute(
            select(DutyDayOverride).where(DutyDayOverride.effective_soldier_id == soldier_id)
        ).scalars().all()
    )
    foreign_override_rows = []
    for o in override_rows:
        owning = session.get(DutyAssignment, o.duty_assignment_id)
        if (
            owning is not None
            and owning.soldier_id != soldier_id
            and owning.status not in excluded_statuses
        ):
            foreign_override_rows.append(o)

    duty_type_cache: dict[uuid.UUID, str] = {}
    spd_cache: dict[uuid.UUID, Decimal] = {}
    location_cache: dict[uuid.UUID, str] = {}

    def _duty_type_name(dt_id: uuid.UUID) -> str:
        if dt_id not in duty_type_cache:
            dt = session.get(DutyType, dt_id)
            duty_type_cache[dt_id] = dt.name if dt else str(dt_id)
            spd_cache[dt_id] = dt.score_per_day if dt else Decimal("0")
        return duty_type_cache[dt_id]

    def _location_name(loc_id: uuid.UUID) -> str:
        if loc_id not in location_cache:
            loc = session.get(DutyLocation, loc_id)
            location_cache[loc_id] = loc.name if loc else str(loc_id)
        return location_cache[loc_id]

    assigned_by_cache: dict[uuid.UUID, str] = {}

    def _assigned_by_name(creator_id: uuid.UUID | None) -> str | None:
        """Resolve DutyAssignment.created_by to the assigner's full name."""
        if creator_id is None:
            return None
        if creator_id not in assigned_by_cache:
            creator = session.get(Soldier, creator_id)
            assigned_by_cache[creator_id] = creator.full_name if creator else None
        return assigned_by_cache[creator_id]

    for a in assignments:
        dt_name = _duty_type_name(a.duty_type_id)
        spd = spd_cache.get(a.duty_type_id, Decimal("0"))
        loc_name = _location_name(a.duty_location_id)

        # Collect dismissals first — needed for score calculation
        dismissals = list(
            session.execute(
                select(DutyDismissal).where(DutyDismissal.duty_assignment_id == a.id)
            ).scalars().all()
        )
        dismissal_ranges = [(d.dismissed_from, d.dismissed_to) for d in dismissals]

        # call_up event — if this assignment has called_up_from set
        if a.called_up_from is not None and a.called_up_to is not None:
            cu_total, cu_formula, cu_segments = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
                date_from=a.called_up_from,
                date_to=a.called_up_to,
            )
            cu_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "assigned_by_name": _assigned_by_name(a.created_by),
                "is_reserve": "true",
                "score_total": cu_total,
                "score_segments": cu_segments,
            }
            if cu_formula:
                cu_metadata["score_formula"] = cu_formula
            events.append(
                TimelineEvent(
                    id=uuid.uuid5(a.id, "call_up"),
                    event_type="call_up",
                    date=a.called_up_from.isoformat(),
                    end_date=_isodate(a.called_up_to),
                    title=f"הוקפץ לרזרבה: {dt_name}",
                    description=a.notes,
                    status=None,
                    metadata=cu_metadata,
                    created_at=a.created_at.isoformat(),
                )
            )

        # cancellation or assignment event
        if a.status == "cancelled":
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="cancellation",
                    date=a.start_date.isoformat(),
                    end_date=_isodate(a.end_date),
                    title=f"בוטלה: {dt_name} ב{loc_name}",
                    description=a.notes,
                    status="cancelled",
                    metadata={
                        "duty_type_name": dt_name,
                        "location_name": loc_name,
                        "duty_assignment_id": str(a.id),
                        "is_reserve": "true" if a.is_reserve else "false",
                        "called_up": "true" if a.called_up_from is not None else "false",
                        "score_total": "0.0",
                    },
                    created_at=a.created_at.isoformat(),
                )
            )
        else:
            asgn_total, asgn_formula, asgn_segments = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
            )
            asgn_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "assigned_by_name": _assigned_by_name(a.created_by),
                "duty_type_id": str(a.duty_type_id),
                "duty_location_id": str(a.duty_location_id),
                "is_reserve": "true" if a.is_reserve else "false",
                "called_up": "true" if a.called_up_from is not None else "false",
                "score_total": asgn_total,
                "score_segments": asgn_segments,
            }
            if a.status == "algorithm_draft":
                job_id_str = session.execute(
                    select(AuditLog.context["job_id"].astext).where(
                        AuditLog.action == "algorithm.proposal.create",
                        AuditLog.entity_id == a.id,
                    ).limit(1)
                ).scalar_one_or_none()
                if job_id_str:
                    asgn_metadata["job_id"] = job_id_str
            if asgn_formula:
                asgn_metadata["score_formula"] = asgn_formula
            events.append(
                TimelineEvent(
                    id=a.id,
                    event_type="assignment",
                    date=a.start_date.isoformat(),
                    end_date=_isodate(a.end_date),
                    title=f"{dt_name} ב{loc_name}",
                    description=a.notes,
                    status=a.status,
                    metadata=asgn_metadata,
                    created_at=a.created_at.isoformat(),
                )
            )

        # dismissal events linked to this assignment
        for d in dismissals:
            dis_total, dis_formula, dis_segments = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
                date_from=d.dismissed_from,
                date_to=d.dismissed_to,
            )
            dis_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "assigned_by_name": _assigned_by_name(a.created_by),
                "score_total": dis_total,
                "score_segments": dis_segments,
            }
            if dis_formula:
                dis_metadata["score_formula"] = dis_formula
            events.append(
                TimelineEvent(
                    id=d.id,
                    event_type="dismissal",
                    date=d.dismissed_from.isoformat(),
                    end_date=_isodate(d.dismissed_to),
                    title=f"שוחרר מתורנות {dt_name}",
                    description=d.reason,
                    status=None,
                    metadata=dis_metadata,
                    created_at=d.created_at.isoformat(),
                )
            )

    # --- DutyDayOverride events (days received via swap, on assignments this
    # soldier doesn't own) — grouped into one event per contiguous run of
    # override days on the same assignment, mirroring the run-merging pattern
    # used by effective_duty_spans (scoring.py). ---
    if foreign_override_rows:
        foreign_assignment_cache: dict[uuid.UUID, DutyAssignment] = {}
        foreign_dismissal_cache: dict[uuid.UUID, list[tuple[date, date]]] = {}

        def _foreign_assignment(aid: uuid.UUID) -> DutyAssignment | None:
            if aid not in foreign_assignment_cache:
                foreign_assignment_cache[aid] = session.get(DutyAssignment, aid)
            return foreign_assignment_cache[aid]

        def _foreign_dismissal_ranges(aid: uuid.UUID) -> list[tuple[date, date]]:
            if aid not in foreign_dismissal_cache:
                rows = session.execute(
                    select(DutyDismissal).where(DutyDismissal.duty_assignment_id == aid)
                ).scalars().all()
                foreign_dismissal_cache[aid] = [(d.dismissed_from, d.dismissed_to) for d in rows]
            return foreign_dismissal_cache[aid]

        sorted_overrides = sorted(
            foreign_override_rows, key=lambda o: (o.duty_assignment_id, o.date)
        )

        runs: list[list[DutyDayOverride]] = []
        for o in sorted_overrides:
            if (
                runs
                and runs[-1][-1].duty_assignment_id == o.duty_assignment_id
                and runs[-1][-1].date == o.date - timedelta(days=1)
            ):
                runs[-1].append(o)
            else:
                runs.append([o])

        for run in runs:
            a = _foreign_assignment(run[0].duty_assignment_id)
            if a is None:
                continue
            dt_name = _duty_type_name(a.duty_type_id)
            spd = spd_cache.get(a.duty_type_id, Decimal("0"))
            loc_name = _location_name(a.duty_location_id)
            dismissal_ranges = _foreign_dismissal_ranges(a.id)

            run_start = run[0].date
            run_end = run[-1].date

            run_total, run_formula, run_segments = _score_parts(
                a,
                dismissal_ranges,
                spd,
                standby_mult,
                called_up_mult,
                dismissed_mult,
                date_from=run_start,
                date_to=run_end,
            )
            run_metadata: dict[str, str | None] = {
                "duty_type_name": dt_name,
                "location_name": loc_name,
                "duty_assignment_id": str(a.id),
                "assigned_by_name": _assigned_by_name(a.created_by),
                "duty_type_id": str(a.duty_type_id),
                "duty_location_id": str(a.duty_location_id),
                "is_reserve": "true" if a.is_reserve else "false",
                "called_up": "false",
                "score_total": run_total,
                "score_segments": run_segments,
                "override_reason": run[0].reason,
            }
            if run_formula:
                run_metadata["score_formula"] = run_formula
            events.append(
                TimelineEvent(
                    id=uuid.uuid5(a.id, f"override:{run_start.isoformat()}"),
                    event_type="assignment",
                    date=run_start.isoformat(),
                    # Exclusive, matching DutyAssignment's own end_date convention.
                    end_date=_isodate(run_end + timedelta(days=1)),
                    title=f"{dt_name} ב{loc_name}",
                    description=a.notes,
                    status=a.status,
                    metadata=run_metadata,
                    created_at=a.created_at.isoformat(),
                )
            )

    # --- RangeAssignment events (current roster membership) ---
    range_location_cache: dict[uuid.UUID, str] = {}

    def _range_location_name(loc_id: uuid.UUID) -> str:
        if loc_id not in range_location_cache:
            loc = session.get(RangeLocation, loc_id)
            range_location_cache[loc_id] = loc.name if loc else str(loc_id)
        return range_location_cache[loc_id]

    range_assignment_filters = [RangeAssignment.soldier_id == soldier_id]
    if not include_drafts:
        range_assignment_filters.append(RangeAssignment.is_draft.is_(False))
    range_assignments = list(
        session.execute(
            select(RangeAssignment).where(*range_assignment_filters)
        ).scalars().all()
    )
    promoted_assignment_ids: set[uuid.UUID] = set(
        session.execute(
            select(RangeExcusalRequest.promoted_assignment_id).where(
                RangeExcusalRequest.promoted_assignment_id.in_(
                    [ra.id for ra in range_assignments]
                )
            )
        ).scalars().all()
    ) if range_assignments else set()
    for ra in range_assignments:
        event = session.get(RangeEvent, ra.range_event_id)
        if event is None:
            continue
        loc_name = _range_location_name(event.range_location_id)
        events.append(
            TimelineEvent(
                id=ra.id,
                event_type="range_assignment",
                date=event.date.isoformat(),
                end_date=None,
                title=f"מטווח {_range_type_he(event.range_type)} ב{loc_name}",
                description=ra.note,
                status=ra.attendance_status,
                metadata={
                    "range_type": event.range_type,
                    "location_name": loc_name,
                    "is_reserve": "true" if ra.is_reserve else "false",
                    "was_promoted_from_reserve": "true" if ra.id in promoted_assignment_ids else "false",
                    "range_event_id": str(event.id),
                },
                created_at=ra.created_at.isoformat(),
            )
        )

    # --- range_removed events (excusal-based and manual removal, unified) ---
    excusal_removals = list(
        session.execute(
            select(RangeExcusalRequest).where(
                RangeExcusalRequest.requested_by == soldier_id,
                RangeExcusalRequest.status == RangeExcusalStatus.approved,
                RangeExcusalRequest.range_assignment_id.is_(None),
                RangeExcusalRequest.range_event_id.is_not(None),
            )
        ).scalars().all()
    )
    for req in excusal_removals:
        event = session.get(RangeEvent, req.range_event_id)
        if event is None:
            continue
        loc_name = _range_location_name(event.range_location_id)
        decider = session.get(Soldier, req.decided_by) if req.decided_by else None
        events.append(
            TimelineEvent(
                id=req.id,
                event_type="range_removed",
                date=event.date.isoformat(),
                end_date=None,
                title=f"הוסר ממטווח {_range_type_he(event.range_type)} ב{loc_name}",
                description=req.reason,
                status=None,
                metadata={
                    "range_type": event.range_type,
                    "location_name": loc_name,
                    "source": "excusal",
                    "range_event_id": str(event.id),
                    "removed_by_name": decider.full_name if decider else None,
                },
                created_at=req.requested_at.isoformat(),
            )
        )

    manual_removal_logs = list(
        session.execute(
            select(AuditLog).where(
                AuditLog.action == "range_assignment.remove",
                AuditLog.before["soldier_id"].astext == str(soldier_id),
            )
        ).scalars().all()
    )
    for log in manual_removal_logs:
        range_event_id_str = (log.before or {}).get("range_event_id")
        if not range_event_id_str:
            continue
        event = session.get(RangeEvent, uuid.UUID(range_event_id_str))
        if event is None:
            continue
        loc_name = _range_location_name(event.range_location_id)
        reason = (log.context or {}).get("reason")
        remover = session.get(Soldier, log.actor_id) if log.actor_id else None
        events.append(
            TimelineEvent(
                id=log.id,
                event_type="range_removed",
                date=event.date.isoformat(),
                end_date=None,
                title=f"הוסר ממטווח {_range_type_he(event.range_type)} ב{loc_name}",
                description=reason,
                status=None,
                metadata={
                    "range_type": event.range_type,
                    "location_name": loc_name,
                    "source": "manual_removal",
                    "range_event_id": str(event.id),
                    "removed_by_name": remover.full_name if remover else None,
                },
                created_at=log.created_at.isoformat(),
            )
        )

    # --- ExemptionRequest events ---
    exemption_type_cache: dict[uuid.UUID, ExemptionType] = {}

    def _exemption_type(et_id: uuid.UUID) -> ExemptionType | None:
        if et_id not in exemption_type_cache:
            et = session.get(ExemptionType, et_id)
            if et is not None:
                exemption_type_cache[et_id] = et
        return exemption_type_cache.get(et_id)

    exemption_duty_type_cache: dict[uuid.UUID, list[str]] = {}

    def _exempted_duty_type_names(et_id: uuid.UUID) -> list[str]:
        if et_id not in exemption_duty_type_cache:
            rows = session.execute(
                select(DutyType.name)
                .join(ExemptionDutyTypeMap, ExemptionDutyTypeMap.duty_type_id == DutyType.id)
                .where(ExemptionDutyTypeMap.exemption_type_id == et_id)
                .order_by(DutyType.name)
            ).scalars().all()
            exemption_duty_type_cache[et_id] = list(rows)
        return exemption_duty_type_cache[et_id]

    exemption_requests = list(
        session.execute(
            select(ExemptionRequest).where(ExemptionRequest.soldier_id == soldier_id)
        ).scalars().all()
    )
    for er in exemption_requests:
        et = _exemption_type(er.exemption_type_id)
        et_name = et.name if et else str(er.exemption_type_id)
        duty_type_names = _exempted_duty_type_names(er.exemption_type_id)
        events.append(
            TimelineEvent(
                id=er.id,
                event_type="exemption_request",
                date=er.start_date.isoformat() if er.start_date else er.created_at.date().isoformat(),
                end_date=_isodate(er.end_date),
                title=f"בקשת פטור: {et_name}",
                description=er.reason,
                status=er.status,
                metadata={
                    "exemption_type_name": et_name,
                    "decision_note": er.decision_note,
                    "exempted_duty_types": json.dumps(duty_type_names, ensure_ascii=False) if duty_type_names else None,
                },
                created_at=er.created_at.isoformat(),
            )
        )

    # --- SoldierExemption events (directly granted, not via a request) ---
    soldier_exemptions = list(
        session.execute(
            select(SoldierExemption).where(SoldierExemption.soldier_id == soldier_id)
        ).scalars().all()
    )
    for se in soldier_exemptions:
        et = _exemption_type(se.exemption_type_id)
        et_name = et.name if et else str(se.exemption_type_id)
        duty_type_names = _exempted_duty_type_names(se.exemption_type_id)
        metadata = {
            "exemption_type_name": et_name,
            "exempted_duty_types": json.dumps(duty_type_names, ensure_ascii=False) if duty_type_names else None,
        }
        if se.revoked_at is not None and include_sensitive:
            revoker = session.get(Soldier, se.revoked_by) if se.revoked_by else None
            metadata["revoked_at"] = se.revoked_at.isoformat()
            metadata["revoked_by_name"] = revoker.full_name if revoker else None
            metadata["revoke_reason"] = se.revoke_reason
        events.append(
            TimelineEvent(
                id=se.id,
                event_type="exemption",
                date=se.start_date.isoformat(),
                end_date=_isodate(se.end_date),
                title=f"פטור: {et_name}",
                description=se.reason,
                status=None,
                metadata=metadata,
                created_at=se.granted_at.isoformat(),
            )
        )

    # --- PersonalConstraint events ---
    constraints = list(
        session.execute(
            select(PersonalConstraint).where(PersonalConstraint.soldier_id == soldier_id)
        ).scalars().all()
    )
    for c in constraints:
        constraint_metadata: dict[str, object] = {
            "decision_note": c.decision_note if include_sensitive else None,
        }
        if c.status == "cancelled" and include_sensitive:
            canceller = session.get(Soldier, c.decided_by) if c.decided_by else None
            constraint_metadata["cancelled_at"] = c.decided_at.isoformat() if c.decided_at else None
            constraint_metadata["cancelled_by_name"] = canceller.full_name if canceller else None
        events.append(
            TimelineEvent(
                id=c.id,
                event_type="personal_constraint",
                date=c.start_date.isoformat(),
                end_date=_isodate(c.end_date),
                title="אילוצים אישיים",
                description=c.reason if include_sensitive else None,
                status=c.status,
                metadata=constraint_metadata,
                created_at=c.created_at.isoformat(),
            )
        )

    # Sort: descending by date, then by created_at descending
    events.sort(key=lambda e: (e.date, e.created_at), reverse=True)
    return events
