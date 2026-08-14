from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import DutyBlock
from app.db.models import RankAdvancementInterval, Soldier
from app.services.eligibility import derive_is_career
from app.services.rank_advancement import compute_next_rank_date, get_next_rank, get_track


@dataclass(frozen=True)
class ProjectedSoldierState:
    rank: str | None
    is_career: bool
    departed: bool


_MAX_CHAIN_STEPS = 24  # safety bound; a soldier cannot realistically advance
                        # more than a couple of ranks within any real duty
                        # planning horizon, this just prevents a runaway loop
                        # on misconfigured (e.g. zero-month) intervals.


def project_soldier_state(
    session: Session,
    *,
    soldier: Soldier,
    as_of: date,
    interval_cache: dict[tuple[str, str], int | None] | None = None,
) -> ProjectedSoldierState:
    """Project a soldier's rank/career/departure state to `as_of`.

    `interval_cache` is an optional pre-loaded {(track, rank): months_to_next}
    map. When given, the rank chain-walk reads its advancement intervals from
    it instead of issuing one single-row SELECT per chain step — the whole
    RankAdvancementInterval table is at most ~21 rows, and bulk callers walk
    the chain for hundreds of (soldier, date) pairs. When omitted the behaviour
    is unchanged (each step queries the DB), so single-shot callers such as
    eligibility.check_soldier_for_assignment need not care.
    """
    rank = soldier.rank
    next_date = soldier.next_rank_date
    for _ in range(_MAX_CHAIN_STEPS):
        if rank is None or next_date is None or next_date > as_of:
            break
        next_rank = get_next_rank(rank)
        if next_rank is None:
            break
        rank = next_rank
        next_date = _next_rank_date(session, rank=rank, since=next_date, interval_cache=interval_cache)

    is_career = derive_is_career(rank, soldier.mandatory_end_date, soldier.discharge_date, today=as_of)

    departed = False
    if soldier.discharge_date is not None and soldier.discharge_date <= as_of:
        departed = True
    if soldier.left_at is not None and soldier.left_at <= as_of:
        departed = True

    return ProjectedSoldierState(rank=rank, is_career=is_career, departed=departed)


def _next_rank_date(
    session: Session,
    *,
    rank: str,
    since: date,
    interval_cache: dict[tuple[str, str], int | None] | None,
) -> date | None:
    """compute_next_rank_date, but served from `interval_cache` when provided."""
    if interval_cache is None:
        return compute_next_rank_date(session, rank=rank, since=since)
    track = get_track(rank)
    if track is None:
        return None
    months = interval_cache.get((track, rank))
    if months is None:
        return None
    return since + relativedelta(months=months)


def _load_interval_cache(session: Session) -> dict[tuple[str, str], int | None]:
    """The whole RankAdvancementInterval table (at most ~21 rows) as a dict."""
    rows = session.execute(select(RankAdvancementInterval)).scalars().all()
    return {(r.track, r.rank): r.months_to_next for r in rows}


def _bulk_exempt_duty_blocks(
    session: Session, *, soldier_ids: Sequence[uuid.UUID], duties: Sequence[DutyBlock]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, duty-block ids covered by an active exemption at any
    point in that block's own [start_date, end_date] span (global, or mapped
    to the block's duty type or location).

    Adapts the exemption resolution eligibility.check_soldier_for_assignment
    does for one soldier/one assignment to many soldiers/many blocks, using
    the same range-overlap convention: an exemption blocks the block if its
    active range overlaps the block's span at all, with a NULL exemption
    end_date meaning open-ended. A DutyBlock can genuinely span several days
    (algorithm_bridge builds blocks straight from a shift's start/end dates,
    and hakpaza's remaining_block spans pull_date..original end), so an
    exemption starting mid-block must still exclude it.
    """
    from app.db.models import (
        ExemptionDutyLocationMap,
        ExemptionDutyTypeMap,
        ExemptionType,
        SoldierExemption,
    )

    if not soldier_ids or not duties:
        return {}

    exemptions = session.execute(
        select(SoldierExemption).where(SoldierExemption.soldier_id.in_(soldier_ids))
    ).scalars().all()
    if not exemptions:
        return {}

    exemption_type_ids = {e.exemption_type_id for e in exemptions}
    types_by_id = {
        et.id: et
        for et in session.execute(
            select(ExemptionType).where(ExemptionType.id.in_(exemption_type_ids))
        ).scalars().all()
    }
    dtype_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in session.execute(
        select(ExemptionDutyTypeMap).where(
            ExemptionDutyTypeMap.exemption_type_id.in_(exemption_type_ids)
        )
    ).scalars().all():
        dtype_map.setdefault(row.exemption_type_id, set()).add(row.duty_type_id)
    loc_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in session.execute(
        select(ExemptionDutyLocationMap).where(
            ExemptionDutyLocationMap.exemption_type_id.in_(exemption_type_ids)
        )
    ).scalars().all():
        loc_map.setdefault(row.exemption_type_id, set()).add(row.duty_location_id)

    by_soldier: dict[uuid.UUID, list[SoldierExemption]] = {}
    for e in exemptions:
        by_soldier.setdefault(e.soldier_id, []).append(e)

    result: dict[uuid.UUID, set[uuid.UUID]] = {}
    for soldier_id, soldier_exemptions in by_soldier.items():
        excluded: set[uuid.UUID] = set()
        for block in duties:
            for e in soldier_exemptions:
                # Range overlap against the block's FULL span, not just its
                # first day -- see the docstring.
                if e.start_date > block.end_date:
                    continue
                if e.end_date is not None and e.end_date < block.start_date:
                    continue
                et = types_by_id.get(e.exemption_type_id)
                if et is not None and et.is_global:
                    excluded.add(block.id)
                    break
                if block.duty_type_id in dtype_map.get(e.exemption_type_id, set()):
                    excluded.add(block.id)
                    break
                if block.duty_location_id in loc_map.get(e.exemption_type_id, set()):
                    excluded.add(block.id)
                    break
        result[soldier_id] = excluded
    return result


def bulk_future_ineligible_duty_blocks(
    session: Session, *, soldier_ids: Sequence[uuid.UUID], duties: Sequence[DutyBlock]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, the set of duty-block ids (among `duties`) they will
    NOT be eligible for over that block's own date span -- covering projected
    rank, service-type/career, mitvahim/alal recency, driving-license expiry,
    active exemptions, and departure.

    A DutyBlock can span several days, so every check here is evaluated over
    the block's whole [start_date, end_date] range rather than its first day.
    A soldier must be eligible for the FULL span to be assignable to it:

    - the rank / service-type portion is evaluated at BOTH `block.start_date`
      and `block.end_date`, and the block is excluded if EITHER fails. These
      two factors are NOT monotonic: moving forward in time a soldier can
      newly LOSE eligibility (promoted past an allowed rank, or their קבע
      transition happens) but can equally newly GAIN it. Checking only
      end_date would let a soldier who is promoted into the required rank on
      day 2 take the whole block including day 1, when they did not yet hold
      it — and would disagree with eligibility.check_soldier_for_assignment,
      which evaluates at the assignment's start_date.
    - recency (mitvahim/alal), driving-license expiry and departure are
      projected to `block.end_date` only. Those are genuinely monotonic —
      they can only ever degrade with time — so a soldier ineligible at
      start_date is necessarily still ineligible at end_date, and end_date
      alone is provably sufficient.
    - exemptions use a true range overlap (see _bulk_exempt_duty_blocks), so
      one starting mid-block still excludes it.

    This matches eligibility.check_soldier_for_assignment's range semantics
    for the manual-assign path. It is deliberately stricter than
    app.services.weapon_eligibility.bulk_ineligible_duty_blocks, whose
    shape/contract this otherwise mirrors -- see that function's docstring for
    why this is a hard per-block exclusion rather than a single soldier-level
    set. Unlike weapon qualification there is no enforcement toggle: none of
    the factors folded in here are optional.
    """
    from app.db.models import DutyType
    from app.services.eligibility import DutyTypeRequirements, _is_eligible
    from app.services.settings_loader import get_setting_int

    if not soldier_ids or not duties:
        return {}

    soldiers = session.execute(
        select(Soldier).where(Soldier.id.in_(soldier_ids))
    ).scalars().all()
    duty_type_ids = {d.duty_type_id for d in duties}
    duty_types = {
        dt.id: dt
        for dt in session.execute(
            select(DutyType).where(DutyType.id.in_(duty_type_ids))
        ).scalars().all()
    }
    mitvahim_months = get_setting_int(session, "eligibility.mitvahim_months", 6)
    alal_months = get_setting_int(session, "eligibility.alal_months", 3)

    # Group blocks by distinct evaluation date -- BOTH endpoints of every block,
    # since the rank/service-type check runs at start_date as well as end_date
    # (see docstring) -- so the (soldier, date) projection is only computed once
    # per date, not once per block. The advancement intervals the chain-walk
    # needs are loaded once here and threaded through: without the cache each
    # chain step of each (soldier, date) pair costs its own single-row SELECT.
    interval_cache = _load_interval_cache(session)
    dates = sorted({d.end_date for d in duties} | {d.start_date for d in duties})
    projections: dict[tuple[uuid.UUID, date], ProjectedSoldierState] = {}
    for s in soldiers:
        for d in dates:
            projections[(s.id, d)] = project_soldier_state(
                session, soldier=s, as_of=d, interval_cache=interval_cache
            )

    # Cache parsed requirements per duty type -- duties usually reuse a handful.
    # `rank_reqs_by_duty_type` is the same requirements narrowed to just the
    # non-monotonic rank/service-type clauses, for the extra start_date pass.
    reqs_by_duty_type: dict[uuid.UUID, DutyTypeRequirements | None] = {}
    rank_reqs_by_duty_type: dict[uuid.UUID, DutyTypeRequirements | None] = {}
    for dt_id, dt in duty_types.items():
        try:
            reqs = DutyTypeRequirements.model_validate(dt.requirements or {})
        except Exception:
            reqs_by_duty_type[dt_id] = None
            rank_reqs_by_duty_type[dt_id] = None
            continue
        reqs_by_duty_type[dt_id] = reqs
        rank_reqs_by_duty_type[dt_id] = (
            DutyTypeRequirements(
                allowed_ranks=reqs.allowed_ranks,
                allowed_service_types=reqs.allowed_service_types,
            )
            if (reqs.allowed_ranks or reqs.allowed_service_types)
            else None
        )

    exempt_blocks = _bulk_exempt_duty_blocks(session, soldier_ids=soldier_ids, duties=duties)

    result: dict[uuid.UUID, set[uuid.UUID]] = {}
    for s in soldiers:
        excluded: set[uuid.UUID] = set(exempt_blocks.get(s.id, set()))
        for block in duties:
            projected = projections[(s.id, block.end_date)]
            if projected.departed:
                excluded.add(block.id)
                continue
            reqs = reqs_by_duty_type.get(block.duty_type_id)
            if reqs is None:
                continue
            if not _is_eligible(
                s, reqs, mitvahim_months=mitvahim_months, alal_months=alal_months,
                today=block.end_date, rank_override=projected.rank,
            ):
                excluded.add(block.id)
                continue
            # Second pass at start_date over the non-monotonic clauses only:
            # the soldier must hold an allowed rank/service type on the block's
            # FIRST day too, not just its last (see docstring).
            rank_reqs = rank_reqs_by_duty_type.get(block.duty_type_id)
            if rank_reqs is None or block.start_date == block.end_date:
                continue
            projected_start = projections[(s.id, block.start_date)]
            if not _is_eligible(
                s, rank_reqs, mitvahim_months=mitvahim_months, alal_months=alal_months,
                today=block.start_date, rank_override=projected_start.rank,
            ):
                excluded.add(block.id)
        if excluded:
            result[s.id] = excluded
    return result
