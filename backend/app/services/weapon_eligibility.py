from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.algorithm.types import DutyBlock
from app.db.models import RangeAssignment, RangeEvent, RangeExcusalRequest, RangeExcusalStatus
from app.services.range_auto_assign import _qualification_types_at_or_above
from app.services.ranges import _validity_days
from app.services.settings_loader import SettingNotFound, get_setting


def _bool_setting(session: Session, key: str, default: bool) -> bool:
    try:
        return bool(get_setting(session, key))
    except SettingNotFound:
        return default


def _enforce_enabled(session: Session) -> bool:
    return _bool_setting(session, "weapon_qualification.enforce_eligibility", True)


def _pending_excusal_disqualifies(session: Session) -> bool:
    return _bool_setting(session, "weapon_qualification.pending_excusal_disqualifies", True)


def _is_eligible_from_data(
    *,
    current_best_valid_until: date | None,
    future_windows: list[tuple[date, date]],
    as_of: date,
) -> bool:
    """Pure predicate shared by the single-soldier and bulk paths.

    current_best_valid_until: the latest valid_until among the soldier's existing
    SoldierRangeQualification rows at/above the required tier (None if none exist).
    future_windows: [(event_date, projected_valid_until), ...] for future, non-reserve,
    non-disqualified RangeAssignments at/above the required tier.
    """
    if current_best_valid_until is not None and current_best_valid_until >= as_of:
        return True
    return any(event_date <= as_of <= projected_valid_until for event_date, projected_valid_until in future_windows)


def _max_qualification_valid_until(
    session: Session, *, soldier_id: uuid.UUID, required_range_type: str,
) -> date | None:
    from app.db.models import SoldierRangeQualification

    candidate_types = _qualification_types_at_or_above(required_range_type)
    rows = session.execute(
        select(SoldierRangeQualification.valid_until).where(
            SoldierRangeQualification.soldier_id == soldier_id,
            SoldierRangeQualification.range_type.in_(candidate_types),
        )
    ).scalars().all()
    return max(rows) if rows else None


def _future_windows(
    session: Session, *, soldier_id: uuid.UUID, required_range_type: str, disqualify_pending: bool,
) -> list[tuple[date, date]]:
    candidate_types = _qualification_types_at_or_above(required_range_type)
    rows = session.execute(
        select(RangeAssignment.id, RangeEvent.date, RangeEvent.range_type)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier_id,
            RangeAssignment.is_reserve.is_(False),
            RangeEvent.range_type.in_(candidate_types),
        )
    ).all()
    if not rows:
        return []

    pending_assignment_ids: set[uuid.UUID] = set()
    if disqualify_pending:
        assignment_ids = [r.id for r in rows]
        pending_assignment_ids = set(
            session.execute(
                select(RangeExcusalRequest.range_assignment_id).where(
                    RangeExcusalRequest.range_assignment_id.in_(assignment_ids),
                    RangeExcusalRequest.status == RangeExcusalStatus.pending,
                )
            ).scalars().all()
        )

    windows: list[tuple[date, date]] = []
    for assignment_id, event_date, range_type in rows:
        if assignment_id in pending_assignment_ids:
            continue
        projected_valid_until = event_date + timedelta(days=_validity_days(session, range_type))
        windows.append((event_date, projected_valid_until))
    return windows


def compute_eligibility(
    session: Session, *, soldier_id: uuid.UUID, required_range_type: str | None, as_of: date,
) -> tuple[bool, str | None]:
    """Return (eligible, reason). reason is None when eligible or when the check
    doesn't apply (required_range_type is None, or the feature is disabled)."""
    if required_range_type is None:
        return True, None
    if not _enforce_enabled(session):
        return True, None

    current_valid_until = _max_qualification_valid_until(
        session, soldier_id=soldier_id, required_range_type=required_range_type,
    )
    future_windows = _future_windows(
        session, soldier_id=soldier_id, required_range_type=required_range_type,
        disqualify_pending=_pending_excusal_disqualifies(session),
    )
    if _is_eligible_from_data(
        current_best_valid_until=current_valid_until, future_windows=future_windows, as_of=as_of,
    ):
        return True, None
    return False, "weapon_qualification"


def bulk_ineligible_duty_blocks(
    session: Session, *, soldier_ids: Sequence[uuid.UUID], duties: Sequence[DutyBlock],
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """For each soldier, the set of duty-block ids (among `duties`) they are NOT
    eligible for due to weapon qualification. Blocks whose `required_range_type`
    is None are never included. Returns {} entirely if the feature is disabled."""
    if not _enforce_enabled(session):
        return {}

    relevant = [d for d in duties if d.required_range_type is not None]
    if not relevant:
        return {}

    disqualify_pending = _pending_excusal_disqualifies(session)
    result: dict[uuid.UUID, set[uuid.UUID]] = {}
    for soldier_id in soldier_ids:
        # Cache per (soldier, required_range_type) — most batches only touch 1-2 tiers.
        cache: dict[str, tuple[date | None, list[tuple[date, date]]]] = {}
        ineligible: set[uuid.UUID] = set()
        for block in relevant:
            required = block.required_range_type
            if required not in cache:
                cache[required] = (
                    _max_qualification_valid_until(session, soldier_id=soldier_id, required_range_type=required),
                    _future_windows(
                        session, soldier_id=soldier_id, required_range_type=required,
                        disqualify_pending=disqualify_pending,
                    ),
                )
            current_valid_until, future_windows = cache[required]
            if not _is_eligible_from_data(
                current_best_valid_until=current_valid_until, future_windows=future_windows,
                as_of=block.start_date,
            ):
                ineligible.add(block.id)
        if ineligible:
            result[soldier_id] = ineligible
    return result
