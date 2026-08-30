from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import DutyBlock
from app.db.models import RangeType, Soldier
from app.services.range_auto_assign import _qualification_types_at_or_above
from app.services.range_coverage import get_projected_range_windows
from app.services.ranges import _validity_days
from app.services.settings_loader import SettingNotFound, get_setting


def _bool_setting(session: Session, key: str, default: bool) -> bool:
    try:
        return bool(get_setting(session, key))
    except SettingNotFound:
        return default


def _mitvachim_enabled(session: Session) -> bool:
    """Hard gate: the ranges module (מטווחים) itself. When it's off, no soldier
    ever has a qualification row and no range events exist, so weapon-qualification
    checks can never be meaningfully evaluated -- this must win regardless of any
    other setting or per-run override."""
    return _bool_setting(session, "mitvachim.enabled", False)


def _enforce_enabled(session: Session) -> bool:
    if not _mitvachim_enabled(session):
        return False
    return _bool_setting(session, "weapon_qualification.enforce_eligibility", True)


def _pending_excusal_disqualifies(session: Session) -> bool:
    return _bool_setting(session, "weapon_qualification.pending_excusal_disqualifies", True)


def _is_eligible_from_data(
    *,
    current_best_valid_until: date | None,
    future_windows: list[tuple[date, date, str]],
    as_of: date,
) -> bool:
    """Pure predicate shared by the single-soldier and bulk paths.

    current_best_valid_until: the latest valid_until among the soldier's existing
    SoldierRangeQualification rows at/above the required tier (None if none exist).
    future_windows: [(event_date, projected_valid_until, range_type), ...] for future, non-reserve,
    non-disqualified RangeAssignments at/above the required tier.
    """
    if current_best_valid_until is not None and current_best_valid_until >= as_of:
        return True
    return any(
        event_date <= as_of <= projected_valid_until
        for event_date, projected_valid_until, _range_type in future_windows
    )


def _max_qualification_valid_untils(
    session: Session,
    *,
    soldier_ids: Sequence[uuid.UUID],
    required_range_types: Sequence[str],
) -> dict[tuple[uuid.UUID, str], date | None]:
    """Batch equivalent of ``_max_qualification_valid_until``.

    The per-soldier helper remains the public internal seam for existing callers;
    this form keeps bulk consumers on the exact same tier rule without N+1 reads.
    """
    unique_soldier_ids = set(soldier_ids)
    unique_required_types = set(required_range_types)
    if not unique_soldier_ids or not unique_required_types:
        return {}
    candidate_types = {
        candidate_type
        for required_range_type in unique_required_types
        for candidate_type in _qualification_types_at_or_above(required_range_type)
    }
    valid_untils: defaultdict[uuid.UUID, dict[str, date]] = defaultdict(dict)
    from app.db.models import SoldierRangeQualification

    for soldier_id, range_type, valid_until in session.execute(
        select(
            SoldierRangeQualification.soldier_id,
            SoldierRangeQualification.range_type,
            SoldierRangeQualification.valid_until,
        ).where(
            SoldierRangeQualification.soldier_id.in_(unique_soldier_ids),
            SoldierRangeQualification.range_type.in_(candidate_types),
        )
    ).all():
        previous = valid_untils[soldier_id].get(range_type)
        if previous is None or valid_until > previous:
            valid_untils[soldier_id][range_type] = valid_until

    return {
        (soldier_id, required_range_type): max(
            (
                valid_untils[soldier_id][range_type]
                for range_type in _qualification_types_at_or_above(required_range_type)
                if range_type in valid_untils[soldier_id]
            ),
            default=None,
        )
        for soldier_id in unique_soldier_ids
        for required_range_type in unique_required_types
    }


def _profile_valid_until(
    session: Session, *, soldier_id: uuid.UUID, required_range_type: str, as_of: date,
) -> date | None:
    """Return the manual profile qualification only after its recorded date.

    ``last_mitvahim_date`` is a generic operational-range date and therefore
    covers laser/live requirements, but a future date must never qualify an
    earlier duty.
    """
    last_mitvahim_date = session.execute(
        select(Soldier.last_mitvahim_date).where(Soldier.id == soldier_id)
    ).scalar_one_or_none()
    if last_mitvahim_date is None or last_mitvahim_date > as_of:
        return None
    valid_untils = [
        last_mitvahim_date + timedelta(days=_validity_days(session, candidate_type))
        for candidate_type in (RangeType.laser, RangeType.live)
        if candidate_type in _qualification_types_at_or_above(required_range_type)
    ]
    return max(valid_untils, default=None)


def _latest_qualification_by_soldier(
    session: Session,
    *,
    soldier_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, tuple[str, date] | None]:
    """Most recent SoldierRangeQualification per soldier, regardless of validity.

    Unlike `_max_qualification_valid_untils`, this does NOT filter by tier or
    exclude expired rows -- it answers "what's the last range this soldier ever
    did at all," used to enrich the "no valid qualification" explanation with
    "last done: <type> on <date>" instead of a bare negative.
    """
    unique_soldier_ids = set(soldier_ids)
    if not unique_soldier_ids:
        return {}
    from app.db.models import SoldierRangeQualification

    latest: dict[uuid.UUID, tuple[str, date]] = {}
    for soldier_id, range_type, valid_until in session.execute(
        select(
            SoldierRangeQualification.soldier_id,
            SoldierRangeQualification.range_type,
            SoldierRangeQualification.valid_until,
        ).where(SoldierRangeQualification.soldier_id.in_(unique_soldier_ids))
    ).all():
        previous = latest.get(soldier_id)
        if previous is None or valid_until > previous[1]:
            latest[soldier_id] = (range_type, valid_until)

    return {soldier_id: latest.get(soldier_id) for soldier_id in unique_soldier_ids}


def _future_windows_by_soldier_and_required_type(
    session: Session,
    *,
    soldier_ids: Sequence[uuid.UUID],
    required_range_types: Sequence[str],
    disqualify_pending: bool,
    future_start: date | None = None,
) -> dict[tuple[uuid.UUID, str], list[tuple[date, date, str]]]:
    """Batch equivalent of ``_future_windows`` using its exact eligibility window.

    ``future_start`` is an explicit clock seam for read-only projections. It
    defaults to real ``date.today()`` so existing production eligibility rules
    never treat a past range as a future qualification window.
    """
    return get_projected_range_windows(
        session,
        soldier_ids=soldier_ids,
        required_range_types=required_range_types,
        future_start=future_start or date.today(),
        disqualify_pending=disqualify_pending,
    )


def _max_qualification_valid_until(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    required_range_type: str,
) -> date | None:
    return _max_qualification_valid_untils(
        session,
        soldier_ids=[soldier_id],
        required_range_types=[required_range_type],
    )[soldier_id, required_range_type]


def _future_windows(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    required_range_type: str,
    disqualify_pending: bool,
) -> list[tuple[date, date, str]]:
    return _future_windows_by_soldier_and_required_type(
        session,
        soldier_ids=[soldier_id],
        required_range_types=[required_range_type],
        disqualify_pending=disqualify_pending,
    )[soldier_id, required_range_type]


def compute_eligibility(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    required_range_type: str | None,
    as_of: date,
) -> tuple[bool, str | None]:
    """Return (eligible, reason). reason is None when eligible or when the check
    doesn't apply (required_range_type is None, or the feature is disabled)."""
    if required_range_type is None:
        return True, None
    if not _enforce_enabled(session):
        return True, None

    current_valid_until = _max_qualification_valid_until(
        session,
        soldier_id=soldier_id,
        required_range_type=required_range_type,
    )
    profile_valid_until = _profile_valid_until(
        session, soldier_id=soldier_id, required_range_type=required_range_type, as_of=as_of,
    )
    if profile_valid_until is not None:
        current_valid_until = max(current_valid_until or profile_valid_until, profile_valid_until)
    future_windows = _future_windows(
        session,
        soldier_id=soldier_id,
        required_range_type=required_range_type,
        disqualify_pending=_pending_excusal_disqualifies(session),
    )
    if _is_eligible_from_data(
        current_best_valid_until=current_valid_until,
        future_windows=future_windows,
        as_of=as_of,
    ):
        return True, None
    return False, "weapon_qualification"


def bulk_ineligible_duty_blocks(
    session: Session,
    *,
    soldier_ids: Sequence[uuid.UUID],
    duties: Sequence[DutyBlock],
    respect_system_toggle: bool = True,
    include_alal: bool = False,
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, the set of duty-block ids (among `duties`) they are NOT
    eligible for due to weapon qualification. Blocks whose `required_range_type`
    is None are never included. Returns {} entirely if the feature is disabled.

    This function has two consumers with different needs around אל"ל:

    - The CP-SAT algorithm bridge (algorithm_bridge.py) uses the result as a
      HARD exclusion from the solver's eligible (duty, soldier) pairs. אל"ל
      eligibility is reactive/warning-only and must never hard-block the
      solver (unlike live/laser, which still do). That caller should pass
      include_alal=False (the default).
    - The manual assign-modal candidates endpoint (routes/shifts.py) uses the
      result purely as an advisory signal -- to show an amber warning marker
      and demote a candidate in sort order before a human manually assigns
      them, never to block anything. אל"ל warnings should keep surfacing
      there exactly like live/laser. That caller should pass
      include_alal=True.

    include_alal: when False (default), blocks requiring "alal" are excluded
    from consideration so they're never hard-blocked. When True, אל"ל blocks
    are treated the same as live/laser and can appear in the result.

    respect_system_toggle: when True (default), short-circuits to {} if either
    מטווחים (mitvachim.enabled) or the weapon_qualification.enforce_eligibility
    master toggle is off -- matching compute_eligibility's behavior, used by
    callers (e.g. the manual assign-modal candidates endpoint) with no notion of
    a per-run override. Callers that have already resolved enforcement through
    their own settings layering (system setting + per-run override), such as the
    algorithm bridge, should pass False here to avoid double-reading the raw
    system setting and silently discarding an explicit per-run override -- מטווחים
    itself still gates the check either way, since no qualification data can
    exist while it's off."""
    if respect_system_toggle:
        if not _enforce_enabled(session):
            return {}
    elif not _mitvachim_enabled(session):
        return {}

    excluded_types: tuple[str | None, ...] = (None,) if include_alal else (None, "alal")
    relevant = [d for d in duties if d.required_range_type not in excluded_types]
    if not relevant:
        return {}

    disqualify_pending = _pending_excusal_disqualifies(session)
    result: dict[uuid.UUID, set[uuid.UUID]] = {}
    for soldier_id in soldier_ids:
        # Cache per (soldier, required_range_type) — most batches only touch 1-2 tiers.
        cache: dict[str, tuple[date | None, list[tuple[date, date, str]]]] = {}
        ineligible: set[uuid.UUID] = set()
        for block in relevant:
            required = block.required_range_type
            if required not in cache:
                cache[required] = (
                    _max_qualification_valid_until(
                        session, soldier_id=soldier_id, required_range_type=required
                    ),
                    _future_windows(
                        session,
                        soldier_id=soldier_id,
                        required_range_type=required,
                        disqualify_pending=disqualify_pending,
                    ),
                )
            current_valid_until, future_windows = cache[required]
            profile_valid_until = _profile_valid_until(
                session, soldier_id=soldier_id, required_range_type=required, as_of=block.start_date,
            )
            if profile_valid_until is not None:
                current_valid_until = max(current_valid_until or profile_valid_until, profile_valid_until)
            if not _is_eligible_from_data(
                current_best_valid_until=current_valid_until,
                future_windows=future_windows,
                as_of=block.start_date,
            ):
                ineligible.add(block.id)
        if ineligible:
            result[soldier_id] = ineligible
    return result
